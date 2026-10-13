import json
import math
import os
import shutil
import threading
import time
from datetime import date
from pathlib import Path

import numpy as np

from .database import SNAPSHOT_DIR, execute, query_all, query_one

MODELS = Path(__file__).resolve().parent.parent / "models"
HELMET_URL = "https://huggingface.co/keremberke/yolov8n-hard-hat-detection/resolve/main/best.pt"
FACE_DET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
FACE_REC_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
FACE_THRESHOLD = 0.363
ALARM_GAP_SECONDS = 20
PRESENCE_SECONDS = 15
TRACKED_CODES = {1, 2, 3, 4, 5}
PHONE_HOLD_SECONDS = 1.0
PHONE_GRACE_SECONDS = 2.5
POSE_POINT_CONF = 0.4

_lock = threading.Lock()
_overlay_lock = threading.Lock()
_state_lock = threading.Lock()
_alarm_lock = threading.Lock()
_boxes: list[dict] = []
_busy = False
_last_run = 0.0
_last_alarm: dict[tuple, float] = {}
_last_frame = None
_person_model = None
_helmet_model = None
_pose_model = None
_face_detector = None
_face_recognizer = None
_model_error = ""
_zone_cache: list = []
_zone_cache_at = 0.0
_zone_cache_stage = ""
_presence = {
    "active": False,
    "until": 0.0,
    "operator": False,
    "operator_name": "",
    "supervisor": False,
    "supervisor_name": "",
    "result": "",
    "detail": "",
}
_empty_since: float | None = None
_leave_latched = False
_dwell_since: dict[int, float] = {}
_dwell_seen: dict[int, float] = {}
_dwell_latched: set[int] = set()
_timer_stage = ""
_phone_since: float | None = None
_phone_seen = 0.0
DWELL_GRACE_SECONDS = 3


def submit_frame(image) -> None:
    global _busy, _last_run
    now = time.time()
    if _busy or now - _last_run < 0.5:
        return
    with _lock:
        if _busy or time.time() - _last_run < 0.5:
            return
        _busy = True
        _last_run = time.time()
    threading.Thread(target=_safe_analyze, args=(image.copy(),), daemon=True).start()


def index_photo(person_id: int, path: str) -> None:
    embedding = _embed_file(path)
    if embedding is None:
        return
    execute("UPDATE people SET face_embedding = ? WHERE id = ?", (embedding.tobytes(), person_id))


def start_presence(seconds: int = PRESENCE_SECONDS) -> dict:
    with _state_lock:
        _presence.update(
            {
                "active": True,
                "until": time.time() + seconds,
                "operator": False,
                "operator_name": "",
                "supervisor": False,
                "supervisor_name": "",
                "result": "",
                "detail": "",
            }
        )
    return presence_status()


def presence_status() -> dict:
    _close_presence()
    with _state_lock:
        remaining = max(0, int(_presence["until"] - time.time())) if _presence["active"] else 0
        return {
            "active": _presence["active"],
            "remaining": remaining,
            "operator": _presence["operator"],
            "operator_name": _presence["operator_name"],
            "supervisor": _presence["supervisor"],
            "supervisor_name": _presence["supervisor_name"],
            "result": _presence["result"],
            "detail": _presence["detail"],
        }


def _clear_dwell_locked() -> None:
    global _empty_since, _leave_latched, _timer_stage
    _empty_since = None
    _leave_latched = False
    _dwell_since.clear()
    _dwell_seen.clear()
    _dwell_latched.clear()
    _timer_stage = ""


def reset_tracking() -> None:
    global _phone_since, _phone_seen
    with _state_lock:
        _clear_dwell_locked()
        _phone_since = None
        _phone_seen = 0.0


def invalidate_zone_cache() -> None:
    global _zone_cache_at
    _zone_cache_at = 0.0


def draw_overlays(image) -> None:
    import cv2

    zone = _cached_zone()
    with _overlay_lock:
        boxes = list(_boxes)
        message = _model_error
    if len(zone) >= 3:
        try:
            height, width = image.shape[:2]
            points = np.array([[int(float(point[0]) * width), int(float(point[1]) * height)] for point in zone], dtype=np.int32)
            cv2.polylines(image, [points], True, (0, 140, 255), 2)
        except Exception:
            pass
    for box in boxes:
        color = box["color"]
        cv2.rectangle(image, (int(box["x1"]), int(box["y1"])), (int(box["x2"]), int(box["y2"])), color, 2)
        cv2.putText(
            image,
            box["label"],
            (int(box["x1"]), max(24, int(box["y1"]) - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
        )
    if message:
        cv2.putText(image, "detect error", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)


def _set_boxes(boxes: list[dict]) -> None:
    global _boxes
    with _overlay_lock:
        _boxes = boxes


def _safe_analyze(image) -> None:
    global _busy
    try:
        _analyze(image)
    except Exception as exc:
        global _model_error
        _model_error = str(exc)
    finally:
        with _lock:
            _busy = False


def _environment_id() -> str:
    row = query_one("SELECT value FROM settings WHERE key = 'environment_id'")
    return row["value"] if row else ""


def _active_codes() -> set[int]:
    environment_id = _environment_id()
    if not environment_id.isdigit():
        return set()
    rows = query_all(
        "SELECT code, enabled FROM environment_detections WHERE environment_id = ?",
        (int(environment_id),),
    )
    return {row["code"] for row in rows if row["enabled"]}


def _analyze(image) -> None:
    global _last_frame
    _last_frame = image
    codes = _active_codes()
    tracked = codes.intersection(TRACKED_CODES)
    if not tracked:
        _set_boxes([])
        _close_presence(image)
        return
    _ensure_models(tracked)
    need_people = bool(tracked.intersection({1, 3}))
    need_faces = 1 in tracked
    need_employee = 2 in tracked
    need_tools = 5 in tracked
    people = _person_boxes(image) if need_people and _person_model is not None else []
    faces = _detect_faces(image) if need_faces and _face_detector is not None else []
    helmets = _helmet_boxes(image) if 3 in tracked and _helmet_model is not None else []
    found_codes = _qr_codes(image) if need_employee or need_tools else []
    employee_codes = [code for code in found_codes if _is_digits(code["text"], 9)] if need_employee else []
    tool_codes = [code for code in found_codes if _is_digits(code["text"], 6)] if need_tools else []
    poses = _pose_people(image) if 4 in tracked and _pose_model is not None else []
    roster = _roster() if need_faces else []
    staff = _enabled_people() if need_employee else []
    tools = _enabled_tools() if need_tools else []
    boxes = []
    for person in people:
        boxes.append({**person, "label": "person", "color": (0, 220, 0)})
    for face in faces:
        x1, y1, x2, y2 = face["bbox"]
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "label": "face", "color": (255, 180, 0)})
    for helmet in helmets:
        boxes.append({**helmet, "label": "helmet", "color": (0, 220, 255)})
    for code in employee_codes:
        matched = _match_employee(code["text"], staff)
        label, color = _qr_label(code["text"], matched)
        boxes.append({"x1": code["x1"], "y1": code["y1"], "x2": code["x2"], "y2": code["y2"], "label": label, "color": color})
    for code in tool_codes:
        tool = _match_tool(code["text"], tools)
        label, color = _tool_label(code["text"], tool)
        boxes.append({"x1": code["x1"], "y1": code["y1"], "x2": code["x2"], "y2": code["y2"], "label": label, "color": color})
    calling = [pose for pose in poses if pose["calling"]]
    for pose in calling:
        boxes.append({"x1": pose["x1"], "y1": pose["y1"], "x2": pose["x2"], "y2": pose["y2"], "label": "phone", "color": (255, 0, 255)})
    _set_boxes(boxes)
    linked = []
    for person in people:
        identity, saw_face = _identity_for_box(person, faces, roster) if need_faces else (None, False)
        linked.append((person, identity, saw_face))
        if saw_face and identity is None and 1 in tracked:
            _raise_alarm(1, "非授权人员进入检测区域", "人脸未登记", "未登记人员", image)
        elif identity and 1 in tracked:
            _alarm_identity(identity, image)
        if 3 in tracked and not _has_helmet(person, helmets):
            _raise_alarm(3, "未佩戴安全防护用品", "未检测到安全帽", identity["name"] if identity else "未登记人员", image)
    if need_employee:
        _check_employee_codes(employee_codes, staff, image)
    if 4 in tracked:
        _check_phone(calling, linked, image)
    if need_tools:
        _check_tool_codes(tool_codes, tools, image)
    _close_presence(image)


def _ensure_models(codes: set[int]) -> bool:
    global _person_model, _helmet_model, _pose_model, _face_detector, _face_recognizer, _model_error
    need_person = bool(codes.intersection({1, 3}))
    need_face = 1 in codes
    need_helmet = 3 in codes
    need_pose = 4 in codes
    if not need_person and not need_face and not need_helmet and not need_pose:
        _model_error = ""
        return True
    try:
        import cv2
        from ultralytics import YOLO

        MODELS.mkdir(parents=True, exist_ok=True)
        if need_person and _person_model is None:
            _person_model = YOLO(_model_file(MODELS / "yolo11n.pt"))
        if need_face and _face_detector is None:
            det_path = MODELS / "face_detection_yunet.onnx"
            rec_path = MODELS / "face_recognition_sface.onnx"
            if not det_path.exists():
                _download(FACE_DET_URL, det_path)
            if not rec_path.exists():
                _download(FACE_REC_URL, rec_path)
            _face_detector = cv2.FaceDetectorYN.create(_model_file(det_path), "", (320, 320), 0.6, 0.3, 5000)
            _face_recognizer = cv2.FaceRecognizerSF.create(_model_file(rec_path), "")
        if need_helmet and _helmet_model is None:
            helmet_path = MODELS / "helmet.pt"
            if not helmet_path.exists():
                _download(HELMET_URL, helmet_path)
            if helmet_path.exists():
                _helmet_model = YOLO(_model_file(helmet_path))
        if need_pose and _pose_model is None:
            _pose_model = YOLO(_model_file(MODELS / "yolo11n-pose.pt"))
        _model_error = ""
        if need_pose and _pose_model is None:
            return False
        return not need_person or _person_model is not None
    except Exception as exc:
        _model_error = str(exc)
        return _person_model is not None or _pose_model is not None


def _model_file(path: Path) -> str:
    text = str(path)
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        cache = Path(os.environ.get("LOCALAPPDATA", ".")) / "safety-models"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / path.name
        if path.exists() and (not target.exists() or target.stat().st_size != path.stat().st_size):
            shutil.copyfile(path, target)
        return str(target)


def _download(url: str, dest: Path) -> None:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def _person_boxes(image) -> list[dict]:
    result = _person_model.predict(image, classes=[0], verbose=False, conf=0.4)[0]
    boxes = []
    if result.boxes is None:
        return boxes
    for box in result.boxes.xyxy.cpu().numpy():
        x1, y1, x2, y2 = [float(v) for v in box]
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return boxes


def _helmet_boxes(image) -> list[dict]:
    result = _helmet_model.predict(image, verbose=False, conf=0.35)[0]
    names = result.names or {}
    boxes = []
    if result.boxes is None:
        return boxes
    for xyxy, cls in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy()):
        label = str(names.get(int(cls), "")).lower().replace("_", "").replace("-", "")
        if "nohardhat" in label or "nohelmet" in label or label in {"head", "barehead"}:
            continue
        if "hardhat" not in label and "helmet" not in label and "安全帽" not in label:
            continue
        x1, y1, x2, y2 = [float(v) for v in xyxy]
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return boxes


def _has_helmet(person: dict, helmets: list[dict]) -> bool:
    head = {"x1": person["x1"], "y1": person["y1"], "x2": person["x2"], "y2": person["y1"] + (person["y2"] - person["y1"]) * 0.45}
    return any(_overlap(head, helmet) > 0.05 for helmet in helmets)


def _detect_faces(image):
    import cv2

    if _face_detector is None or _face_recognizer is None:
        return []
    height, width = image.shape[:2]
    scale = 1280 / max(height, width, 1)
    if scale < 1:
        resized = cv2.resize(image, (int(width * scale), int(height * scale)))
    else:
        resized = image
        scale = 1.0
    resized_height, resized_width = resized.shape[:2]
    _face_detector.setInputSize((resized_width, resized_height))
    _, faces = _face_detector.detect(resized)
    found = []
    if faces is None:
        return found
    for face in faces:
        aligned = _face_recognizer.alignCrop(resized, face)
        embedding = _face_recognizer.feature(aligned).flatten().astype(np.float32)
        x, y, box_w, box_h = [float(v) / scale for v in face[:4]]
        found.append({"bbox": (x, y, x + box_w, y + box_h), "embedding": embedding})
    return found


def _roster() -> list[dict]:
    rows = query_all(
        """
        SELECT id, name, list_type, role, qualification_expiry, badge_no, enabled, face_embedding
        FROM people WHERE enabled = 1
        """
    )
    roster = []
    for row in rows:
        raw = row.get("face_embedding")
        if not raw:
            continue
        vector = np.frombuffer(raw, dtype=np.float32)
        norm = np.linalg.norm(vector)
        if norm == 0:
            continue
        row["vector"] = vector / norm
        roster.append(row)
    return roster


def _identity_for_box(person: dict, faces, roster: list[dict]):
    best = None
    best_score = FACE_THRESHOLD
    saw_face = False
    for face in faces:
        center = ((face["bbox"][0] + face["bbox"][2]) / 2, (face["bbox"][1] + face["bbox"][3]) / 2)
        if not (person["x1"] <= center[0] <= person["x2"] and person["y1"] <= center[1] <= person["y2"]):
            continue
        saw_face = True
        embedding = np.asarray(face["embedding"], dtype=np.float32)
        embedding = embedding / max(np.linalg.norm(embedding), 1e-6)
        for person_row in roster:
            score = float(np.dot(embedding, person_row["vector"]))
            if score > best_score:
                best_score = score
                best = person_row
    return best, saw_face


def _alarm_identity(person: dict, image) -> None:
    if person["list_type"] == "black":
        if not _enabled(1):
            return
        _raise_alarm(1, "黑名单人员出现", "人脸比对命中黑名单", person["name"], image)
        return
    if person["list_type"] == "white" and _expired(person.get("qualification_expiry") or ""):
        if _enabled(1):
            _raise_alarm(1, "资质过期人员试图作业", "白名单人员资质已过期", person["name"], image)
        return
    if person["list_type"] not in {"white", "black"} and _enabled(1):
        _raise_alarm(1, "非授权人员进入检测区域", "人脸未登记", person["name"], image)


def _alarm_badge(person_box: dict, identity: dict, codes_found: list[dict], roster: list[dict], image) -> None:
    if not _enabled(2) or not identity.get("badge_no"):
        return
    for code in codes_found:
        if not _point_in(code["x"], code["y"], person_box):
            continue
        text = code["text"].strip()
        if text == identity["badge_no"]:
            return
        owner = next((item for item in roster if item.get("badge_no") and item["badge_no"] == text), None)
        detail = f"人脸为{identity['name']}，工牌为{owner['name'] if owner else text}"
        _raise_alarm(2, "代检/人证不符", detail, identity["name"], image)
        return


def _qr_codes(image) -> list[dict]:
    found = []
    seen = set()
    _collect_opencv_codes(image, found, seen)
    if not found:
        import cv2

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _collect_opencv_codes(gray, found, seen)
    _collect_zbar_codes(image, found, seen)
    return found


def _collect_opencv_codes(image, found: list[dict], seen: set[str]) -> None:
    import cv2

    detector = cv2.QRCodeDetector()
    before = len(found)
    try:
        ok, texts, points, _straight = detector.detectAndDecodeMulti(image)
    except Exception:
        ok, texts, points = False, [], None
    if ok and points is not None:
        for text, quad in zip(texts, points):
            if quad is None:
                continue
            xs = [float(point[0]) for point in quad]
            ys = [float(point[1]) for point in quad]
            _append_code(found, seen, text, xs, ys)
    if len(found) > before:
        return
    try:
        text, points, _straight = detector.detectAndDecode(image)
    except Exception:
        return
    if points is None or len(points) == 0:
        return
    quad = points[0] if len(getattr(points, "shape", ())) == 3 else points
    xs = [float(point[0]) for point in quad]
    ys = [float(point[1]) for point in quad]
    _append_code(found, seen, text, xs, ys)


def _collect_zbar_codes(image, found: list[dict], seen: set[str]) -> None:
    try:
        from pyzbar.pyzbar import decode
    except Exception:
        return
    for item in decode(image):
        if not item.polygon:
            continue
        xs = [float(point.x) for point in item.polygon]
        ys = [float(point.y) for point in item.polygon]
        _append_code(found, seen, item.data.decode("utf-8", errors="ignore"), xs, ys)


def _append_code(found: list[dict], seen: set[str], text: str, xs: list[float], ys: list[float]) -> None:
    text = (text or "").strip()
    if not text or not xs or text in seen:
        return
    seen.add(text)
    found.append(
        {
            "text": text,
            "x": sum(xs) / len(xs),
            "y": sum(ys) / len(ys),
            "x1": min(xs),
            "y1": min(ys),
            "x2": max(xs),
            "y2": max(ys),
        }
    )


def _is_digits(text: str, length: int) -> bool:
    value = (text or "").strip()
    return value.isdigit() and len(value) == length


def _enabled_people() -> list[dict]:
    return query_all(
        """
        SELECT id, name, list_type, employee_no, qualification_expiry
        FROM people WHERE enabled = 1
        """
    )


def _enabled_tools() -> list[dict]:
    return query_all(
        "SELECT name, tool_no, qr_text, calibration_expiry FROM tools WHERE enabled = 1"
    )


def _match_tool(text: str, tools: list[dict]):
    key = (text or "").strip()
    if not key:
        return None
    return next(
        (
            item
            for item in tools
            if key == (item.get("tool_no") or "").strip() or key == (item.get("qr_text") or "").strip()
        ),
        None,
    )


def _tool_label(text: str, tool: dict | None) -> tuple[str, tuple]:
    number = _ascii_label(text.strip(), "tool")
    if not tool:
        return _ascii_label(f"unknown {text.strip()}", "unknown"), (0, 0, 255)
    if _expired(tool.get("calibration_expiry") or ""):
        return _ascii_label(f"expired {text.strip()}", "expired"), (0, 140, 255)
    return number, (0, 220, 0)


def _check_tool_codes(codes_found: list[dict], tools: list[dict], image) -> None:
    for code in codes_found:
        text = code["text"].strip()
        if not _is_digits(text, 6):
            continue
        tool = _match_tool(text, tools)
        if not tool:
            _raise_alarm(5, "使用未登记工器具", f"6 位编号 {text} 不在工器具库", text, image)
            continue
        expiry = tool.get("calibration_expiry") or ""
        if _expired(expiry):
            _raise_alarm(
                5,
                "使用超期未检定仪器/工器具",
                f"{tool['name']} 检定已于 {expiry} 到期",
                tool["name"],
                image,
            )


def _match_employee(text: str, people: list[dict]):
    key = (text or "").strip()
    if not key:
        return None
    matches = [person for person in people if (person.get("employee_no") or "").strip() == key]
    if not matches:
        return None
    blacks = [person for person in matches if person["list_type"] == "black"]
    return blacks[0] if blacks else matches[0]


def _qr_label(text: str, person: dict | None) -> tuple[str, tuple]:
    number = _ascii_label(text.strip(), "qr")
    if not person:
        return number, (0, 255, 255)
    if person["list_type"] == "black":
        return _ascii_label(f"blacklist {text.strip()}", "blacklist"), (0, 0, 255)
    if person["list_type"] == "white" and _expired(person.get("qualification_expiry") or ""):
        return _ascii_label(f"expired {text.strip()}", "expired"), (0, 140, 255)
    return number, (0, 220, 0)


def _ascii_label(text: str, fallback: str) -> str:
    cleaned = " ".join(text.split())
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError:
        return fallback
    return cleaned[:32] or fallback


def _check_employee_codes(codes_found: list[dict], people: list[dict], image) -> None:
    for code in codes_found:
        person = _match_employee(code["text"], people)
        if not person:
            continue
        number = (person.get("employee_no") or code["text"]).strip()
        if not _is_digits(code["text"], 9):
            continue
        if person["list_type"] == "black":
            if _enabled(2):
                _raise_alarm(2, "黑名单人员出现", f"工号二维码命中黑名单：{number}", person["name"], image)
            continue
        expiry = person.get("qualification_expiry") or ""
        if person["list_type"] == "white" and _expired(expiry) and _enabled(2):
            _raise_alarm(2, "资质过期人员试图作业", f"工号二维码对应资质已于 {expiry} 到期", person["name"], image)


def _pose_people(image) -> list[dict]:
    result = _pose_model.predict(image, verbose=False, conf=0.4)[0]
    poses = []
    if result.keypoints is None or result.boxes is None:
        return poses
    points_all = result.keypoints.xy.cpu().numpy()
    conf_tensor = result.keypoints.conf
    scores_all = conf_tensor.cpu().numpy() if conf_tensor is not None else None
    for index, box in enumerate(result.boxes.xyxy.cpu().numpy()):
        point_scores = scores_all[index] if scores_all is not None else np.ones(len(points_all[index]))
        x1, y1, x2, y2 = [float(value) for value in box]
        poses.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "calling": _wrist_at_ear(points_all[index], point_scores),
            }
        )
    return poses


def _keypoint(points, scores, index: int):
    if index >= len(points) or float(scores[index]) < POSE_POINT_CONF:
        return None
    x, y = float(points[index][0]), float(points[index][1])
    if x <= 0 and y <= 0:
        return None
    return x, y


def _wrist_at_ear(points, scores) -> bool:
    nose = _keypoint(points, scores, 0)
    left_shoulder = _keypoint(points, scores, 5)
    right_shoulder = _keypoint(points, scores, 6)
    if nose is None or left_shoulder is None or right_shoulder is None:
        return False
    shoulder_width = math.hypot(left_shoulder[0] - right_shoulder[0], left_shoulder[1] - right_shoulder[1])
    if shoulder_width < 8:
        return False
    sides = (
        (_keypoint(points, scores, 9), _keypoint(points, scores, 7)),
        (_keypoint(points, scores, 10), _keypoint(points, scores, 8)),
    )
    for wrist, elbow in sides:
        if wrist is None or elbow is None:
            continue
        if wrist[1] >= left_shoulder[1] and wrist[1] >= right_shoulder[1]:
            continue
        if wrist[1] < nose[1] - 0.15 * shoulder_width:
            continue
        distance = math.hypot(wrist[0] - nose[0], wrist[1] - nose[1])
        if distance < 0.35 * shoulder_width or distance > 1.1 * shoulder_width:
            continue
        if abs(wrist[0] - nose[0]) < 0.2 * shoulder_width:
            continue
        shoulder_y = left_shoulder[1] if wrist[0] <= nose[0] else right_shoulder[1]
        if elbow[1] > shoulder_y + 0.5 * shoulder_width:
            continue
        return True
    return False


def _check_phone(calling: list[dict], linked: list, image) -> None:
    global _phone_since, _phone_seen
    now = time.time()
    with _state_lock:
        if not calling:
            return
        if _phone_since is None or now - _phone_seen > PHONE_GRACE_SECONDS:
            _phone_since = now
        _phone_seen = now
        ready = now - _phone_since >= PHONE_HOLD_SECONDS
    if not ready:
        return
    identity = _identity_for_pose(calling[0], linked)
    name = identity["name"] if identity and identity.get("name") else "现场"
    _raise_alarm(4, "违规操作动作", "作业中接打电话", name, image)


def _identity_for_pose(pose: dict, linked: list):
    best = None
    best_overlap = 0.3
    for person, identity, _saw_face in linked:
        overlap = _overlap(pose, person)
        if identity and overlap > best_overlap:
            best_overlap = overlap
            best = identity
    return best


def _check_intrusion(linked: list, zone: list, image) -> None:
    if len(zone) < 3:
        return
    height, width = image.shape[:2]
    for person, identity, _saw_face in linked:
        center_x = (person["x1"] + person["x2"]) / 2
        center_y = (person["y1"] + person["y2"]) / 2
        if not _point_in_polygon(center_x, center_y, zone, width, height):
            continue
        name = identity["name"] if identity else "未登记人员"
        _raise_alarm(6, "越界进入试验区", "人员进入电子围栏", name, image)


def _check_dwell(linked: list, zone: list, image) -> None:
    global _empty_since, _leave_latched, _timer_stage
    stage = _stage()
    if not _test_running() or len(zone) < 3:
        with _state_lock:
            _clear_dwell_locked()
        return
    height, width = image.shape[:2]
    inside = []
    for person, identity, _saw_face in linked:
        center_x = (person["x1"] + person["x2"]) / 2
        center_y = (person["y1"] + person["y2"]) / 2
        if _point_in_polygon(center_x, center_y, zone, width, height):
            inside.append(identity)
    now = time.time()
    leave_seconds = max(5, _setting_int("leave_seconds", 30))
    dwell_minutes = max(1, _setting_int("dwell_minutes", 10))
    pending = []
    with _state_lock:
        if _timer_stage != stage:
            _clear_dwell_locked()
            _timer_stage = stage
        if inside:
            _empty_since = None
            _leave_latched = False
        else:
            if _empty_since is None:
                _empty_since = now
            elif not _leave_latched and now - _empty_since >= leave_seconds:
                _leave_latched = True
                pending.append((7, "离岗", f"围栏内连续 {leave_seconds} 秒无人", "现场"))
        seen = set()
        for identity in inside:
            if not identity:
                continue
            person_id = int(identity["id"])
            seen.add(person_id)
            _dwell_seen[person_id] = now
            started = _dwell_since.get(person_id)
            if started is None:
                _dwell_since[person_id] = now
                started = now
            if person_id not in _dwell_latched and now - started >= dwell_minutes * 60:
                _dwell_latched.add(person_id)
                pending.append((7, "长时间滞留", f"{identity['name']} 在围栏内超过 {dwell_minutes} 分钟", identity["name"]))
        for person_id in list(_dwell_since):
            if person_id in seen:
                continue
            if now - _dwell_seen.get(person_id, 0) <= DWELL_GRACE_SECONDS:
                continue
            _dwell_since.pop(person_id, None)
            _dwell_seen.pop(person_id, None)
            _dwell_latched.discard(person_id)
    for code, title, detail, person in pending:
        _raise_alarm(code, title, detail, person, image)


def _check_tools(codes_found: list[dict], employee_texts: set[str], image) -> None:
    if not codes_found:
        return
    tools = query_all(
        "SELECT name, tool_no, qr_text, calibration_expiry FROM tools WHERE enabled = 1"
    )
    for code in codes_found:
        text = code["text"].strip()
        if not text or text in employee_texts:
            continue
        tool = next(
            (
                item
                for item in tools
                if text == (item.get("qr_text") or "").strip() or text == (item.get("tool_no") or "").strip()
            ),
            None,
        )
        if not tool or not _expired(tool.get("calibration_expiry") or ""):
            continue
        _raise_alarm(
            10,
            "使用超期未检定仪器/工器具",
            f"{tool['name']} 检定已于 {tool['calibration_expiry']} 到期",
            tool["name"],
            image,
        )


def _note_presence(identity: dict) -> None:
    if not identity or identity.get("list_type") != "white":
        return
    role = identity.get("role")
    with _state_lock:
        if not _presence["active"]:
            return
        if role == "operator" and not _presence["operator"]:
            _presence["operator"] = True
            _presence["operator_name"] = identity["name"]
        elif role == "supervisor" and not _presence["supervisor"]:
            _presence["supervisor"] = True
            _presence["supervisor_name"] = identity["name"]


def _close_presence(image=None) -> None:
    with _state_lock:
        if not _presence["active"]:
            return
        complete = _presence["operator"] and _presence["supervisor"]
        if not complete and time.time() < _presence["until"]:
            return
        _presence["active"] = False
        missing = []
        if not _presence["operator"]:
            missing.append("操作人")
        if not _presence["supervisor"]:
            missing.append("监护人")
        if not missing:
            _presence["result"] = "ok"
            _presence["detail"] = "操作人与监护人均已到岗"
            return
        _presence["result"] = "alarm"
        _presence["detail"] = "未识别到" + "、".join(missing)
        detail = _presence["detail"]
        person = "、".join(missing)
    if _enabled(3):
        _raise_alarm(3, "试验人员缺位/监护缺失", detail, person, image if image is not None else _last_frame)


def _embed_file(path: str):
    if not _ensure_models({1}):
        return None
    import cv2

    image = cv2.imread(path)
    if image is None:
        return None
    faces = _detect_faces(image)
    if not faces:
        return None
    face = max(faces, key=lambda item: (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]))
    vector = np.asarray(face["embedding"], dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm == 0:
        return None
    return vector / norm


def _raise_alarm(code: int, title: str, detail: str, person: str, image=None) -> None:
    key = (code, person)
    now = time.time()
    with _alarm_lock:
        if now - _last_alarm.get(key, 0) < ALARM_GAP_SECONDS:
            return
        _last_alarm[key] = now
    alarm_id = execute(
        """
        INSERT INTO alarms (code, title, detail, person, stage, simulated)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (code, title, detail, person, _stage()),
    )
    if image is None or not alarm_id:
        return
    path = _save_snapshot(alarm_id, image)
    if path:
        execute("UPDATE alarms SET snapshot_path = ? WHERE id = ?", (path, alarm_id))


def _save_snapshot(alarm_id: int, image) -> str:
    import cv2

    canvas = image.copy()
    zone = _cached_zone()
    height, width = canvas.shape[:2]
    if len(zone) >= 3:
        points = np.array([[int(point[0] * width), int(point[1] * height)] for point in zone], dtype=np.int32)
        cv2.polylines(canvas, [points], True, (0, 140, 255), 2)
    with _overlay_lock:
        boxes = list(_boxes)
    for box in boxes:
        cv2.rectangle(canvas, (int(box["x1"]), int(box["y1"])), (int(box["x2"]), int(box["y2"])), box["color"], 2)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return ""
    path = SNAPSHOT_DIR / f"{alarm_id}.jpg"
    path.write_bytes(encoded.tobytes())
    return str(path)


def _cached_zone() -> list:
    global _zone_cache, _zone_cache_at, _zone_cache_stage
    stage = _environment_id()
    now = time.time()
    if stage == _zone_cache_stage and now - _zone_cache_at < 0.5:
        return _zone_cache
    row = query_one("SELECT points FROM zones WHERE stage = ?", (stage,))
    points = []
    if row and row.get("points"):
        try:
            loaded = json.loads(row["points"])
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            points = [point for point in loaded if isinstance(point, list) and len(point) == 2]
    _zone_cache = points
    _zone_cache_at = now
    _zone_cache_stage = stage
    return points


def _stage() -> str:
    environment_id = _environment_id()
    if not environment_id.isdigit():
        return ""
    row = query_one("SELECT name FROM environments WHERE id = ?", (int(environment_id),))
    return row["name"] if row else ""


def _setting_int(key: str, default: int) -> int:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    if not row:
        return default
    try:
        return int(row["value"])
    except ValueError:
        return default


def _test_running() -> bool:
    row = query_one("SELECT value FROM settings WHERE key = 'test_running'")
    return bool(row and row["value"] == "1")


def _enabled(code: int) -> bool:
    return code in _active_codes()


def _expired(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    try:
        return date.fromisoformat(text) < date.today()
    except ValueError:
        return False


def _overlap(a: dict, b: dict) -> float:
    x1, y1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    x2, y2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area = max(1, (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]))
    return inter / area


def _point_in(x: float, y: float, box: dict) -> bool:
    return box["x1"] <= x <= box["x2"] and box["y1"] <= y <= box["y2"]


def _point_in_polygon(x: float, y: float, points: list, width: int, height: int) -> bool:
    polygon = [(float(point[0]) * width, float(point[1]) * height) for point in points]
    inside = False
    previous = len(polygon) - 1
    for index, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[previous]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        previous = index
    return inside
