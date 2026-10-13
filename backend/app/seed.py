from .database import execute, query_all, query_one

DETECTIONS = [
    {
        "code": 1,
        "category": "check",
        "category_name": "检测项",
        "title": "人员检测",
        "method": "摄像机比对人脸。未登记、黑名单，以及白名单资质过期都会报警。",
        "problem": "无关人员或资质失效人员进入作业现场",
        "stages": "",
    },
    {
        "code": 2,
        "category": "check",
        "category_name": "检测项",
        "title": "二维码工号检测",
        "method": "识别 9 位数字工号二维码，与人员名单比对。黑名单或资质过期则报警。",
        "problem": "工号二维码对应黑名单或资质过期人员",
        "stages": "",
    },
    {
        "code": 3,
        "category": "check",
        "category_name": "检测项",
        "title": "安全护具佩戴检测",
        "method": "检测人员是否佩戴安全帽，未佩戴则报警。",
        "problem": "未佩戴安全帽进入作业现场",
        "stages": "",
    },
    {
        "code": 4,
        "category": "check",
        "category_name": "检测项",
        "title": "危险动作检测",
        "method": "识别作业中接打电话，手腕贴在耳侧约 1 秒即报警。",
        "problem": "作业中接打电话",
        "stages": "",
    },
    {
        "code": 5,
        "category": "check",
        "category_name": "检测项",
        "title": "二维码工器具检测",
        "method": "识别 6 位数字器具二维码。未录入或检定到期则报警。",
        "problem": "使用未登记或超期未检定的工器具",
        "stages": "",
    },
]

DETECTION_CODES = [item["code"] for item in DETECTIONS]


def seed_detections() -> None:
    for item in DETECTIONS:
        existing = query_one("SELECT code FROM detections WHERE code = ?", (item["code"],))
        if existing:
            execute(
                """
                UPDATE detections
                SET category = ?, category_name = ?, title = ?, method = ?, problem = ?, stages = ?
                WHERE code = ?
                """,
                (
                    item["category"],
                    item["category_name"],
                    item["title"],
                    item["method"],
                    item["problem"],
                    item["stages"],
                    item["code"],
                ),
            )
            continue
        execute(
            """
            INSERT INTO detections
                (code, category, category_name, title, method, problem, stages, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                item["code"],
                item["category"],
                item["category_name"],
                item["title"],
                item["method"],
                item["problem"],
                item["stages"],
            ),
        )


def seed_environments() -> None:
    if not query_one("SELECT id FROM environments LIMIT 1"):
        for index, name in enumerate(("环境1", "环境2", "环境3"), start=1):
            execute("INSERT INTO environments (name, sort_order) VALUES (?, ?)", (name, index))
    environments = query_all("SELECT id FROM environments ORDER BY sort_order, id")
    for environment in environments:
        for code in DETECTION_CODES:
            execute(
                """
                INSERT OR IGNORE INTO environment_detections (environment_id, code, enabled)
                VALUES (?, ?, 0)
                """,
                (environment["id"], code),
            )
    current = query_one("SELECT value FROM settings WHERE key = 'environment_id'")
    valid = {str(environment["id"]) for environment in environments}
    if current and current["value"] in valid:
        return
    first = str(environments[0]["id"])
    old = query_one("SELECT value FROM settings WHERE key = 'stage'")
    old_name = old["value"] if old else ""
    if old_name and old_name not in valid:
        old_camera = query_one("SELECT * FROM stage_cameras WHERE stage = ?", (old_name,))
        if old_camera and not query_one("SELECT stage FROM stage_cameras WHERE stage = ?", (first,)):
            execute(
                """
                INSERT INTO stage_cameras (stage, device_index, device_name, source_type, stream_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    first,
                    old_camera["device_index"],
                    old_camera["device_name"],
                    old_camera.get("source_type") or "local",
                    old_camera.get("stream_url") or "",
                ),
            )
    execute(
        """
        INSERT INTO settings (key, value) VALUES ('environment_id', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (first,),
    )
    execute(
        """
        INSERT INTO settings (key, value) VALUES ('stage', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (first,),
    )
