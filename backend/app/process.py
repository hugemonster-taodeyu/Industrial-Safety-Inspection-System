import itertools
import threading

from . import detect

WIRING_PARTS = (
    "connect_terminal_a",
    "connect_terminal_b",
    "connect_terminal_c",
    "connect_ground_terminal",
)
LABELS = {
    "terminal": "裸露接线端子",
    "connect_terminal_a": "连接端子A",
    "connect_terminal_b": "连接端子B",
    "connect_terminal_c": "连接端子C",
    "cable_connect_terminal": "高压接线端子",
    "ground_terminal": "地线端子",
    "connect_ground_terminal": "连接地线端子",
    "stick_head": "导电棒尖端",
    "person": "戴安全帽人员",
}

_lock = threading.Lock()
_detail_model = None
_device = 0
_running = False
_sides = {"left": False, "right": False, "front": False, "back": False}
_parts = {name: False for name in WIRING_PARTS}
_passed = [False, False, False, False]


def _fresh() -> None:
    global _sides, _parts, _passed
    _sides = {"left": False, "right": False, "front": False, "back": False}
    _parts = {name: False for name in WIRING_PARTS}
    _passed = [False, False, False, False]


def _current() -> int:
    for index, passed in enumerate(_passed):
        if not passed:
            return index
    return len(_passed)


def _status(boxes: list[dict] | None = None) -> dict:
    return {
        "running": _running,
        "current": _current(),
        "steps": [
            {"name": "启动", "passed": _passed[0]},
            {"name": "检查变压器", "passed": _passed[1], "sides": dict(_sides)},
            {"name": "接线", "passed": _passed[2], "parts": dict(_parts)},
            {"name": "放电", "passed": _passed[3]},
        ],
        "boxes": boxes or [],
    }


def _ensure_detail() -> None:
    global _detail_model
    if _detail_model is not None:
        return
    from ultralytics import YOLO

    path = detect.MODELS / "best.pt"
    if not path.exists():
        raise FileNotFoundError("未找到变压器细节模型 best.pt")
    _detail_model = YOLO(detect._model_file(path))


def start_process() -> dict:
    global _running
    detect._ensure_models({3})
    if detect._person_model is None or detect._helmet_model is None:
        raise RuntimeError(detect._model_error or "人员或安全帽模型未就绪")
    _ensure_detail()
    with _lock:
        _fresh()
        _running = True
        return _status()


def stop_process() -> dict:
    global _running
    with _lock:
        _running = False
        return _status()


def analyze_process_frame(image) -> dict:
    if not _running:
        return _status()
    height, width = image.shape[:2]
    details = _detail_boxes(image)
    boxes = [_public_box(item, width, height) for item in details]
    with _lock:
        step = _current() if _running else -1
    people = _helmeted_people(image) if step == 1 else []
    for person in people:
        boxes.append(_public_box({**person, "name": "person"}, width, height))
    with _lock:
        if not _running:
            return _status(boxes)
        step = _current()
        if step == 0:
            if any(item["name"] == "connect_ground_terminal" for item in details):
                _passed[0] = True
        elif step == 1:
            _mark_sides(_transformer_box(details), people)
            if all(_sides.values()):
                _passed[1] = True
        elif step == 2:
            for item in details:
                if item["name"] in _parts:
                    _parts[item["name"]] = True
            if all(_parts.values()):
                _passed[2] = True
        if _current() == 3:
            _passed[3] = True
        return _status(boxes)


def _predict(model, image, **kwargs):
    global _device
    try:
        return model.predict(image, device=_device, verbose=False, **kwargs)[0]
    except Exception:
        if _device == "cpu":
            raise
        _device = "cpu"
        return model.predict(image, device=_device, verbose=False, **kwargs)[0]


def _detail_boxes(image) -> list[dict]:
    result = _predict(_detail_model, image, imgsz=1280, conf=0.25)
    names = result.names or {}
    boxes = []
    if result.boxes is None:
        return boxes
    for xyxy, cls in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy()):
        name = str(names.get(int(cls), ""))
        x1, y1, x2, y2 = [float(value) for value in xyxy]
        boxes.append({"name": name, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return boxes


def _helmeted_people(image) -> list[dict]:
    person_result = _predict(detect._person_model, image, classes=[0], imgsz=1280, conf=0.4)
    helmet_result = _predict(detect._helmet_model, image, imgsz=1280, conf=0.35)
    people = []
    if person_result.boxes is not None:
        for xyxy in person_result.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = [float(value) for value in xyxy]
            people.append({"name": "person", "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    helmets = []
    names = helmet_result.names or {}
    if helmet_result.boxes is not None:
        for xyxy, cls in zip(helmet_result.boxes.xyxy.cpu().numpy(), helmet_result.boxes.cls.cpu().numpy()):
            label = str(names.get(int(cls), "")).lower().replace("_", "").replace("-", "")
            if "nohardhat" in label or "nohelmet" in label or label in {"head", "barehead"}:
                continue
            if "hardhat" not in label and "helmet" not in label and "安全帽" not in label:
                continue
            x1, y1, x2, y2 = [float(value) for value in xyxy]
            helmets.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return [person for person in people if detect._has_helmet(person, helmets)]


def _public_box(box: dict, width: int, height: int) -> dict:
    return {
        "x1": box["x1"] / width,
        "y1": box["y1"] / height,
        "x2": box["x2"] / width,
        "y2": box["y2"] / height,
        "name": box["name"],
        "label": LABELS.get(box["name"], box["name"]),
    }


def _transformer_box(details: list[dict]) -> dict | None:
    terminals = [item for item in details if item["name"] == "terminal"]
    if len(terminals) < 3:
        return None
    best = None
    best_score = 1e9
    for combo in itertools.combinations(terminals, 3):
        centers_y = [((item["y1"] + item["y2"]) / 2) for item in combo]
        centers_x = [((item["x1"] + item["x2"]) / 2) for item in combo]
        heights = [item["y2"] - item["y1"] for item in combo]
        mean_height = max(sum(heights) / 3, 1)
        y_spread = max(centers_y) - min(centers_y)
        x_spread = max(centers_x) - min(centers_x)
        if x_spread < mean_height or y_spread > mean_height * 1.2:
            continue
        score = y_spread / x_spread
        if score < best_score:
            best_score = score
            best = combo
    if best is None:
        return None
    return {
        "x1": min(item["x1"] for item in best),
        "y1": min(item["y1"] for item in best),
        "x2": max(item["x2"] for item in best),
        "y2": max(item["y2"] for item in best),
    }


def _mark_sides(transformer: dict | None, people: list[dict]) -> None:
    if transformer is None:
        return
    width = max(transformer["x2"] - transformer["x1"], 1)
    height = max(transformer["y2"] - transformer["y1"], 1)
    reach_x = width * 2.5
    reach_y = height * 3
    for person in people:
        center_x = (person["x1"] + person["x2"]) / 2
        center_y = (person["y1"] + person["y2"]) / 2
        near_row = transformer["y1"] - reach_y <= center_y <= transformer["y2"] + reach_y
        near_col = transformer["x1"] - reach_x <= center_x <= transformer["x2"] + reach_x
        behind = center_y < (transformer["y1"] + transformer["y2"]) / 2
        if center_x < transformer["x1"] and near_row:
            _sides["left"] = True
            _sides["back"] = True
        if center_x > transformer["x2"] and near_row:
            _sides["right"] = True
            _sides["back"] = True
        if behind and center_y < transformer["y1"] and near_col:
            _sides["back"] = True
        if center_y > transformer["y2"] and near_col:
            _sides["front"] = True
