import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .camera import (
    active_camera,
    connect_camera,
    disconnect_camera,
    last_error,
    list_cameras,
    mjpeg_frames,
    same_camera,
)
from .database import PHOTO_DIR, SNAPSHOT_DIR, execute, init_db, query_all, query_one
from .detect import invalidate_zone_cache, presence_status, reset_tracking, start_presence
from .seed import DETECTION_CODES, seed_detections, seed_environments

app = FastAPI(title="工程行为安全检测系统")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


class ToggleBody(BaseModel):
    enabled: bool


class BulkBody(BaseModel):
    category: str
    enabled: bool


class PersonBody(BaseModel):
    list_type: str
    name: str
    employee_no: str = ""
    role: str = ""
    qualification_expiry: str = ""
    badge_no: str = ""
    reason: str = ""
    enabled: bool = True


class SettingsBody(BaseModel):
    stage: str | None = None
    sound_enabled: bool | None = None
    leave_seconds: int | None = Field(default=None, ge=5, le=600)
    dwell_minutes: int | None = Field(default=None, ge=1, le=180)
    test_running: bool | None = None


class ZoneBody(BaseModel):
    points: list[list[float]]


class ToolBody(BaseModel):
    tool_no: str = ""
    name: str
    calibration_expiry: str = ""
    qr_text: str = ""
    enabled: bool = True


class AckBody(BaseModel):
    acknowledged: bool = True


class CameraBody(BaseModel):
    source: str = "local"
    device_index: int | None = None
    device_name: str = ""
    stream_url: str = ""


class SimulateBody(BaseModel):
    code: int = Field(ge=1, le=5)
    person: str = ""


class EnvironmentBody(BaseModel):
    name: str = ""


class PresenceBody(BaseModel):
    person_id: int | None = None


def _person_row(row: dict) -> dict:
    row.pop("face_embedding", None)
    row["enabled"] = bool(row["enabled"])
    if row.get("photo_path"):
        row["photo_url"] = f"/api/photos/{Path(row['photo_path']).name}"
    else:
        row["photo_url"] = ""
    return row


def _alarm_row(row: dict) -> dict:
    row["simulated"] = bool(row["simulated"])
    row["acknowledged"] = bool(row.get("acknowledged"))
    snapshot = row.pop("snapshot_path", "") or ""
    row["snapshot_url"] = f"/api/snapshots/{Path(snapshot).name}" if snapshot else ""
    return row


def _tool_row(row: dict) -> dict:
    row["enabled"] = bool(row["enabled"])
    return row


def _setting_value(key: str, default: str) -> str:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def _put_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _detection_row(row: dict) -> dict:
    row["enabled"] = bool(row["enabled"])
    return row


@app.on_event("startup")
def on_startup() -> None:
    import threading

    init_db()
    seed_detections()
    seed_environments()
    threading.Thread(target=_apply_stage_camera, args=(_current_stage(),), daemon=True).start()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stages")
def stages():
    return {"stages": query_all("SELECT id, name FROM environments ORDER BY sort_order, id")}


@app.get("/api/settings")
def get_settings():
    try:
        leave_seconds = int(_setting_value("leave_seconds", "30"))
    except ValueError:
        leave_seconds = 30
    try:
        dwell_minutes = int(_setting_value("dwell_minutes", "10"))
    except ValueError:
        dwell_minutes = 10
    return {
        "stage": _current_stage(),
        "stage_name": _current_environment_name(),
        "sound_enabled": _setting_value("sound_enabled", "0") == "1",
        "sound_available": True,
        "leave_seconds": leave_seconds,
        "dwell_minutes": dwell_minutes,
        "test_running": _setting_value("test_running", "0") == "1",
    }


@app.patch("/api/settings")
def update_settings(body: SettingsBody):
    if body.stage is not None:
        if not body.stage.isdigit() or not query_one("SELECT id FROM environments WHERE id = ?", (int(body.stage),)):
            raise HTTPException(400, "未知环境")
        _put_setting("environment_id", body.stage)
        _put_setting("stage", body.stage)
        _apply_stage_camera(body.stage)
        reset_tracking()
    if body.sound_enabled is not None:
        _put_setting("sound_enabled", "1" if body.sound_enabled else "0")
    if body.leave_seconds is not None:
        _put_setting("leave_seconds", str(body.leave_seconds))
    if body.dwell_minutes is not None:
        _put_setting("dwell_minutes", str(body.dwell_minutes))
    if body.test_running is not None:
        _put_setting("test_running", "1" if body.test_running else "0")
        reset_tracking()
    return get_settings()


def _stage_camera(stage: str) -> dict | None:
    return query_one("SELECT * FROM stage_cameras WHERE stage = ?", (stage,))


def _apply_stage_camera(stage: str) -> None:
    row = _stage_camera(stage)
    if not row:
        disconnect_camera()
        return
    source = row.get("source_type") or "local"
    url = row.get("stream_url") or ""
    if same_camera(source, row["device_index"], url):
        return
    connect_camera(source, row["device_index"], row["device_name"], url)


def _camera_payload() -> dict:
    stage = _current_stage()
    saved = _stage_camera(stage)
    active = active_camera()
    configured = saved is not None
    if not saved:
        connected = False
    elif (saved.get("source_type") or "local") == "network":
        connected = bool(active["connected"] and active["stream_url"] == (saved.get("stream_url") or ""))
    else:
        connected = bool(active["connected"] and active["device_index"] == saved["device_index"])
    return {
        "connected": connected,
        "configured": configured,
        "source": (saved.get("source_type") if saved else "") or "",
        "device_index": saved["device_index"] if saved else None,
        "device_name": saved["device_name"] if saved else "",
        "stream_url": saved.get("stream_url") if saved else "",
        "stage": stage,
        "width": active.get("width") or 0,
        "height": active.get("height") or 0,
    }


def _current_environment_id() -> int | None:
    raw = _setting_value("environment_id", "")
    if not raw.isdigit():
        return None
    return int(raw)


def _current_environment_name() -> str:
    environment_id = _current_environment_id()
    if environment_id is None:
        return ""
    row = query_one("SELECT name FROM environments WHERE id = ?", (environment_id,))
    return row["name"] if row else ""


def _environment_enabled(code: int) -> bool:
    environment_id = _current_environment_id()
    if environment_id is None:
        return False
    row = query_one(
        "SELECT enabled FROM environment_detections WHERE environment_id = ? AND code = ?",
        (environment_id, code),
    )
    return bool(row and row["enabled"])


def _set_environment_detection(environment_id: int, code: int, enabled: bool) -> None:
    execute(
        """
        INSERT INTO environment_detections (environment_id, code, enabled)
        VALUES (?, ?, ?)
        ON CONFLICT(environment_id, code) DO UPDATE SET enabled = excluded.enabled
        """,
        (environment_id, code, 1 if enabled else 0),
    )


@app.get("/api/detections")
def list_detections():
    environment_id = _current_environment_id()
    enabled = {}
    if environment_id is not None:
        for item in query_all(
            "SELECT code, enabled FROM environment_detections WHERE environment_id = ?",
            (environment_id,),
        ):
            enabled[item["code"]] = bool(item["enabled"])
    result = []
    for row in query_all("SELECT * FROM detections WHERE code IN (1, 2, 3, 4, 5) ORDER BY code"):
        item = _detection_row(row)
        item["enabled"] = enabled.get(row["code"], False)
        item["relevant"] = True
        result.append(item)
    return result


@app.patch("/api/detections/{code}")
def toggle_detection(code: int, body: ToggleBody):
    if code not in DETECTION_CODES:
        raise HTTPException(404, "检测项不存在")
    environment_id = _current_environment_id()
    if environment_id is None:
        raise HTTPException(400, "尚未选择环境")
    _set_environment_detection(environment_id, code, body.enabled)
    return next(item for item in list_detections() if item["code"] == code)


@app.post("/api/detections/bulk")
def bulk_toggle(body: BulkBody):
    if body.category != "check":
        raise HTTPException(400, "未知分组")
    environment_id = _current_environment_id()
    if environment_id is None:
        raise HTTPException(400, "尚未选择环境")
    for code in DETECTION_CODES:
        _set_environment_detection(environment_id, code, body.enabled)
    return list_detections()


def _next_environment_name() -> str:
    names = {row["name"] for row in query_all("SELECT name FROM environments")}
    index = 1
    while f"环境{index}" in names:
        index += 1
    return f"环境{index}"


@app.post("/api/environments")
def create_environment(body: EnvironmentBody):
    name = body.name.strip() or _next_environment_name()
    if query_one("SELECT id FROM environments WHERE name = ?", (name,)):
        raise HTTPException(400, "环境名称已存在")
    sort_row = query_one("SELECT COALESCE(MAX(sort_order), 0) AS value FROM environments")
    environment_id = execute(
        "INSERT INTO environments (name, sort_order) VALUES (?, ?)",
        (name, int(sort_row["value"]) + 1 if sort_row else 1),
    )
    for code in DETECTION_CODES:
        _set_environment_detection(environment_id, code, False)
    _put_setting("environment_id", str(environment_id))
    _put_setting("stage", str(environment_id))
    _apply_stage_camera(str(environment_id))
    reset_tracking()
    return {"id": environment_id, "name": name, "stage": str(environment_id)}


@app.patch("/api/environments/{environment_id}")
def rename_environment(environment_id: int, body: EnvironmentBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if not query_one("SELECT id FROM environments WHERE id = ?", (environment_id,)):
        raise HTTPException(404, "环境不存在")
    if query_one("SELECT id FROM environments WHERE name = ? AND id != ?", (name, environment_id)):
        raise HTTPException(400, "环境名称已存在")
    execute("UPDATE environments SET name = ? WHERE id = ?", (name, environment_id))
    return {"id": environment_id, "name": name}


@app.delete("/api/environments/{environment_id}")
def delete_environment(environment_id: int):
    existing = query_one("SELECT id, name FROM environments WHERE id = ?", (environment_id,))
    if not existing:
        raise HTTPException(404, "环境不存在")
    remaining = query_all("SELECT id FROM environments WHERE id != ? ORDER BY sort_order, id", (environment_id,))
    if not remaining:
        raise HTTPException(400, "至少保留一个环境")
    key = str(environment_id)
    execute("DELETE FROM environment_detections WHERE environment_id = ?", (environment_id,))
    execute("DELETE FROM stage_cameras WHERE stage = ?", (key,))
    execute("DELETE FROM zones WHERE stage = ?", (key,))
    execute("DELETE FROM environments WHERE id = ?", (environment_id,))
    if _current_environment_id() == environment_id:
        next_id = str(remaining[0]["id"])
        _put_setting("environment_id", next_id)
        _put_setting("stage", next_id)
        _apply_stage_camera(next_id)
        reset_tracking()
        invalidate_zone_cache()
    return {"ok": True, "stage": _current_stage()}


@app.get("/api/people")
def list_people(list_type: str | None = None):
    if list_type:
        if list_type not in ("white", "black"):
            raise HTTPException(400, "名单类型无效")
        rows = query_all(
            "SELECT * FROM people WHERE list_type = ? ORDER BY id DESC",
            (list_type,),
        )
    else:
        rows = query_all("SELECT * FROM people ORDER BY id DESC")
    return [_person_row(row) for row in rows]


@app.post("/api/people")
def create_person(body: PersonBody):
    if body.list_type not in ("white", "black"):
        raise HTTPException(400, "名单类型无效")
    if not body.name.strip():
        raise HTTPException(400, "姓名不能为空")
    if body.list_type == "white" and body.role not in ("operator", "supervisor"):
        raise HTTPException(400, "白名单角色需为操作人或监护人")
    person_id = execute(
        """
        INSERT INTO people
            (list_type, name, employee_no, role, qualification_expiry, badge_no, reason, enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            body.list_type,
            body.name.strip(),
            _clean_employee_no(body.employee_no),
            body.role if body.list_type == "white" else "",
            body.qualification_expiry if body.list_type == "white" else "",
            body.badge_no.strip() if body.list_type == "white" else "",
            body.reason.strip() if body.list_type == "black" else "",
            1 if body.enabled else 0,
        ),
    )
    return _person_row(query_one("SELECT * FROM people WHERE id = ?", (person_id,)))


@app.patch("/api/people/{person_id}")
def update_person(person_id: int, body: PersonBody):
    existing = query_one("SELECT * FROM people WHERE id = ?", (person_id,))
    if not existing:
        raise HTTPException(404, "人员不存在")
    if body.list_type not in ("white", "black"):
        raise HTTPException(400, "名单类型无效")
    if not body.name.strip():
        raise HTTPException(400, "姓名不能为空")
    if body.list_type == "white" and body.role not in ("operator", "supervisor"):
        raise HTTPException(400, "白名单角色需为操作人或监护人")
    execute(
        """
        UPDATE people SET
            list_type = ?, name = ?, employee_no = ?, role = ?,
            qualification_expiry = ?, badge_no = ?, reason = ?, enabled = ?
        WHERE id = ?
        """,
        (
            body.list_type,
            body.name.strip(),
            _clean_employee_no(body.employee_no),
            body.role if body.list_type == "white" else "",
            body.qualification_expiry if body.list_type == "white" else "",
            body.badge_no.strip() if body.list_type == "white" else "",
            body.reason.strip() if body.list_type == "black" else "",
            1 if body.enabled else 0,
            person_id,
        ),
    )
    return _person_row(query_one("SELECT * FROM people WHERE id = ?", (person_id,)))


@app.delete("/api/people/{person_id}")
def delete_person(person_id: int):
    existing = query_one("SELECT * FROM people WHERE id = ?", (person_id,))
    if not existing:
        raise HTTPException(404, "人员不存在")
    if existing["photo_path"]:
        path = Path(existing["photo_path"])
        if path.exists():
            path.unlink()
    execute("DELETE FROM people WHERE id = ?", (person_id,))
    return {"ok": True}


@app.post("/api/people/{person_id}/photo")
async def upload_photo(person_id: int, file: UploadFile = File(...)):
    existing = query_one("SELECT * FROM people WHERE id = ?", (person_id,))
    if not existing:
        raise HTTPException(404, "人员不存在")
    suffix = Path(file.filename or "face.jpg").suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "仅支持 jpg、png、webp")
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    dest = PHOTO_DIR / f"{person_id}{suffix}"
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "照片不能超过 5MB")
    dest.write_bytes(data)
    for other in PHOTO_DIR.glob(f"{person_id}.*"):
        if other != dest:
            other.unlink()
    execute("UPDATE people SET photo_path = ? WHERE id = ?", (str(dest), person_id))
    from .detect import index_photo

    index_photo(person_id, str(dest))
    return _person_row(query_one("SELECT * FROM people WHERE id = ?", (person_id,)))


@app.get("/api/photos/{filename}")
def get_photo(filename: str):
    path = (PHOTO_DIR / filename).resolve()
    if PHOTO_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "照片不存在")
    return FileResponse(path)


@app.patch("/api/alarms/{alarm_id}")
def acknowledge_alarm(alarm_id: int, body: AckBody):
    row = query_one("SELECT id FROM alarms WHERE id = ?", (alarm_id,))
    if not row:
        raise HTTPException(404, "报警不存在")
    execute("UPDATE alarms SET acknowledged = ? WHERE id = ?", (1 if body.acknowledged else 0, alarm_id))
    return _alarm_row(query_one("SELECT * FROM alarms WHERE id = ?", (alarm_id,)))


@app.get("/api/snapshots/{filename}")
def get_snapshot(filename: str):
    path = (SNAPSHOT_DIR / filename).resolve()
    if SNAPSHOT_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "抓拍不存在")
    return FileResponse(path)


@app.get("/api/alarms")
def list_alarms(code: int | None = None):
    if code is None:
        rows = query_all("SELECT * FROM alarms ORDER BY id DESC LIMIT 200")
    else:
        rows = query_all(
            "SELECT * FROM alarms WHERE code = ? ORDER BY id DESC LIMIT 200",
            (code,),
        )
    return [_alarm_row(row) for row in rows]


def _current_stage() -> str:
    environment_id = _current_environment_id()
    if environment_id is None:
        return ""
    return str(environment_id)


def _clean_employee_no(value: str) -> str:
    text = value.strip()
    if text and not (text.isdigit() and len(text) == 9):
        raise HTTPException(400, "工号需为 9 位数字")
    return text


def _qualification_expired(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    try:
        return date.fromisoformat(text) < date.today()
    except ValueError:
        return False


def _create_alarm(code: int, title: str, detail: str, person: str, stage: str) -> dict:
    alarm_id = execute(
        """
        INSERT INTO alarms (code, title, detail, person, stage, simulated)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (code, title, detail, person, stage),
    )
    return _alarm_row(query_one("SELECT * FROM alarms WHERE id = ?", (alarm_id,)))


@app.post("/api/alarms/simulate-presence")
def simulate_presence(body: PresenceBody):
    stage = _current_environment_name()
    personnel_on = _environment_enabled(1)
    person = None
    if body.person_id is not None:
        person = query_one("SELECT * FROM people WHERE id = ?", (body.person_id,))
        if not person:
            raise HTTPException(404, "人员不存在")
        if not person["enabled"]:
            return {
                "alarm": None,
                "level": "muted",
                "title": "该人员已停用",
                "detail": "停用人员不参与名单判断",
                "person": person["name"],
                "stage": stage,
            }

    if person and person["list_type"] == "black":
        if not personnel_on:
            return {
                "alarm": None,
                "level": "muted",
                "title": "黑名单人员未报警",
                "detail": "当前环境未开启人员检测",
                "person": person["name"],
                "stage": stage,
            }
        alarm = _create_alarm(
            1,
            "黑名单人员出现",
            "模拟名单：命中黑名单",
            person["name"],
            stage,
        )
        return {"alarm": alarm, "level": "alarm", "title": alarm["title"], "detail": alarm["detail"], "person": alarm["person"], "stage": stage}

    if person and person["list_type"] == "white":
        if _qualification_expired(person["qualification_expiry"]):
            if not personnel_on:
                return {
                    "alarm": None,
                    "level": "muted",
                    "title": "资质过期未报警",
                    "detail": "当前环境未开启人员检测",
                    "person": person["name"],
                    "stage": stage,
                }
            alarm = _create_alarm(
                1,
                "资质过期人员试图作业",
                "模拟名单：白名单人员资质已过期",
                person["name"],
                stage,
            )
            return {"alarm": alarm, "level": "alarm", "title": alarm["title"], "detail": alarm["detail"], "person": alarm["person"], "stage": stage}
        return {
            "alarm": None,
            "level": "ok",
            "title": "白名单人员，不报警",
            "detail": "在白名单且资质未过期",
            "person": person["name"],
            "stage": stage,
        }

    if not personnel_on:
        return {
            "alarm": None,
            "level": "muted",
            "title": "未登记人员未报警",
            "detail": "当前环境未开启人员检测",
            "person": "未登记人员",
            "stage": stage,
        }
    alarm = _create_alarm(
        1,
        "非授权人员进入检测区域",
        "模拟名单：不在白名单或黑名单",
        "未登记人员",
        stage,
    )
    return {"alarm": alarm, "level": "alarm", "title": alarm["title"], "detail": alarm["detail"], "person": alarm["person"], "stage": stage}


@app.post("/api/alarms/simulate")
def simulate_alarm(body: SimulateBody):
    detection = query_one("SELECT * FROM detections WHERE code = ?", (body.code,))
    if not detection or detection["code"] not in DETECTION_CODES:
        raise HTTPException(404, "检测项不存在")
    if not _environment_enabled(detection["code"]):
        raise HTTPException(400, "该检测项未开启，无法报警")
    stage = _current_environment_name()
    person = body.person.strip() or "未登记人员"
    detail = f"模拟触发：{detection['title']}"
    alarm_id = execute(
        """
        INSERT INTO alarms (code, title, detail, person, stage, simulated)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (detection["code"], detection["title"], detail, person, stage),
    )
    return _alarm_row(query_one("SELECT * FROM alarms WHERE id = ?", (alarm_id,)))


def _current_zone() -> dict:
    stage = _current_stage()
    row = query_one("SELECT points FROM zones WHERE stage = ?", (stage,))
    points = []
    if row and row.get("points"):
        try:
            loaded = json.loads(row["points"])
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            points = loaded
    return {"stage": stage, "points": points}


@app.get("/api/zone")
def get_zone():
    return _current_zone()


@app.put("/api/zone")
def save_zone(body: ZoneBody):
    if len(body.points) < 3:
        raise HTTPException(400, "围栏至少需要 3 个点")
    cleaned = []
    for point in body.points:
        if len(point) != 2:
            raise HTTPException(400, "坐标无效")
        x, y = float(point[0]), float(point[1])
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise HTTPException(400, "坐标需在画面范围内")
        cleaned.append([round(x, 4), round(y, 4)])
    stage = _current_stage()
    execute(
        """
        INSERT INTO zones (stage, points) VALUES (?, ?)
        ON CONFLICT(stage) DO UPDATE SET points = excluded.points
        """,
        (stage, json.dumps(cleaned, ensure_ascii=False)),
    )
    invalidate_zone_cache()
    return {"stage": stage, "points": cleaned}


@app.delete("/api/zone")
def delete_zone():
    stage = _current_stage()
    execute("DELETE FROM zones WHERE stage = ?", (stage,))
    invalidate_zone_cache()
    reset_tracking()
    return {"stage": stage, "points": []}


@app.get("/api/presence")
def get_presence():
    return presence_status()


@app.post("/api/presence/start")
def begin_presence():
    detection = query_one("SELECT enabled FROM detections WHERE code = 3")
    if not detection or not detection["enabled"]:
        raise HTTPException(400, "检测项 3 未开启")
    return start_presence()


@app.get("/api/tools")
def list_tools():
    return [_tool_row(row) for row in query_all("SELECT * FROM tools ORDER BY id DESC")]


def _save_tool_fields(body: ToolBody) -> tuple:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    tool_no = body.tool_no.strip()
    if not (tool_no.isdigit() and len(tool_no) == 6):
        raise HTTPException(400, "编号需为 6 位数字，并作为二维码内容")
    return (tool_no, name, body.calibration_expiry.strip(), tool_no, 1 if body.enabled else 0)


@app.post("/api/tools")
def create_tool(body: ToolBody):
    fields = _save_tool_fields(body)
    tool_id = execute(
        """
        INSERT INTO tools (tool_no, name, calibration_expiry, qr_text, enabled)
        VALUES (?, ?, ?, ?, ?)
        """,
        fields,
    )
    return _tool_row(query_one("SELECT * FROM tools WHERE id = ?", (tool_id,)))


@app.patch("/api/tools/{tool_id}")
def update_tool(tool_id: int, body: ToolBody):
    existing = query_one("SELECT id FROM tools WHERE id = ?", (tool_id,))
    if not existing:
        raise HTTPException(404, "工器具不存在")
    fields = _save_tool_fields(body)
    execute(
        """
        UPDATE tools SET tool_no = ?, name = ?, calibration_expiry = ?, qr_text = ?, enabled = ?
        WHERE id = ?
        """,
        (*fields, tool_id),
    )
    return _tool_row(query_one("SELECT * FROM tools WHERE id = ?", (tool_id,)))


@app.delete("/api/tools/{tool_id}")
def delete_tool(tool_id: int):
    existing = query_one("SELECT id FROM tools WHERE id = ?", (tool_id,))
    if not existing:
        raise HTTPException(404, "工器具不存在")
    execute("DELETE FROM tools WHERE id = ?", (tool_id,))
    return {"ok": True}


@app.get("/api/cameras")
def cameras():
    return list_cameras()


@app.post("/api/camera/connect")
def connect(body: CameraBody):
    source = body.source
    if source not in ("local", "network"):
        raise HTTPException(400, "未知摄像头类型")
    stage = _current_stage()
    if source == "network":
        url = body.stream_url.strip()
        if not url.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            raise HTTPException(400, "地址需以 rtsp://、http:// 或 https:// 开头")
        name = body.device_name.strip() or url.split("@")[-1]
        if not connect_camera("network", -1, name, url):
            raise HTTPException(400, last_error() or "网络摄像头连接失败")
        execute(
            """
            INSERT INTO stage_cameras (stage, device_index, device_name, source_type, stream_url)
            VALUES (?, -1, ?, 'network', ?)
            ON CONFLICT(stage) DO UPDATE SET
                device_index = -1,
                device_name = excluded.device_name,
                source_type = 'network',
                stream_url = excluded.stream_url
            """,
            (stage, name, url),
        )
        return _camera_payload()
    if body.device_index is None:
        raise HTTPException(400, "请选择本机摄像头")
    devices = [item for item in list_cameras() if item.get("ready")]
    match = next((item for item in devices if item["index"] == body.device_index), None)
    if not match:
        raise HTTPException(400, "未找到该摄像头")
    name = body.device_name.strip() or match["name"]
    if not connect_camera("local", body.device_index, name):
        raise HTTPException(400, last_error() or "摄像头连接失败")
    execute(
        """
        INSERT INTO stage_cameras (stage, device_index, device_name, source_type, stream_url)
        VALUES (?, ?, ?, 'local', '')
        ON CONFLICT(stage) DO UPDATE SET
            device_index = excluded.device_index,
            device_name = excluded.device_name,
            source_type = 'local',
            stream_url = ''
        """,
        (stage, body.device_index, name),
    )
    return _camera_payload()


@app.get("/api/camera/status")
def status():
    return _camera_payload()


@app.get("/api/camera/stream")
def stream():
    return StreamingResponse(
        mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
