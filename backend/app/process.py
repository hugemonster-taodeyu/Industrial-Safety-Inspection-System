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
    "person": "人员",
}

_lock = threading.Lock()
_detail_model = None
_device = 0
_running = False
_sides = {"left": False, "right": False, "front": False, "back": False}
_parts = {name: False for name in WIRING_PARTS}
_start = {"terminal": False, "ground_terminal": False}
_passed = [False, False, False]
_layout = None
_layout_seen = None
_stable_since = None
_fixed_box = None
_fixed_terminals = None
_box_updated_at = None
_last_time = None
_front_since = None
LIMB_POINTS = (11, 12, 13, 14, 15, 16)
LIMB_CONF = 0.55
STABLE_SECONDS = 10
UPDATE_SECONDS = 5
FRONT_SECONDS = 0.4


def _fresh() -> None:
    global _sides, _parts, _start, _passed, _layout, _layout_seen, _stable_since
    global _fixed_box, _fixed_terminals, _box_updated_at, _last_time, _front_since
    _sides = {"left": False, "right": False, "front": False, "back": False}
    _parts = {name: False for name in WIRING_PARTS}
    _start = {"terminal": False, "ground_terminal": False}
    _passed = [False, False, False]
    _layout = None
    _layout_seen = None
    _stable_since = None
    _fixed_box = None
    _fixed_terminals = None
    _box_updated_at = None
    _last_time = None
    _front_since = None


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
    detect._ensure_models({4})
    if detect._pose_model is None:
        raise RuntimeError(detect._model_error or "姿态模型未就绪")
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


def analyze_process_frame(image, video_time: float = 0) -> dict:
    if not _running:
        return _status()
    height, width = image.shape[:2]
    details = _detail_boxes(image)
    boxes = [_public_box(item, width, height) for item in details]
    with _lock:
        step = _current() if _running else -1
    poses = _poses(image) if step == 1 else []
    for pose in poses:
        boxes.append(_public_box({**pose, "name": "person"}, width, height))
    with _lock:
        if not _running:
            return _status(boxes)
        _note_time(video_time)
        step = _current()
        if step == 0:
            _observe_startup(details, video_time)
            step = _current()
        if step in (1, 2):
            _refresh_transformer(details, video_time)
        if step == 1:
            _mark_sides(_fixed_box, poses, details, video_time)
            if all(_sides.values()):
                _passed[1] = True
        elif step == 2:
            for item in details:
                if item["name"] in _parts:
                    _parts[item["name"]] = True
            if all(_parts.values()):
                _passed[2] = True
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


def _poses(image) -> list[dict]:
    result = _predict(detect._pose_model, image, conf=0.4)
    poses = []
    if result.keypoints is None or result.boxes is None:
        return poses
    points_all = result.keypoints.xy.cpu().numpy()
    conf_tensor = result.keypoints.conf
    scores_all = conf_tensor.cpu().numpy() if conf_tensor is not None else None
    for index, box in enumerate(result.boxes.xyxy.cpu().numpy()):
        points = points_all[index]
        scores = scores_all[index] if scores_all is not None else [1.0] * len(points)
        x1, y1, x2, y2 = [float(value) for value in box]
        left_shoulder = detect._keypoint(points, scores, 5)
        right_shoulder = detect._keypoint(points, scores, 6)
        shoulder = None
        if left_shoulder is not None and right_shoulder is not None:
            shoulder = (
                (left_shoulder[0] + right_shoulder[0]) / 2,
                (left_shoulder[1] + right_shoulder[1]) / 2,
            )
        limb_points = []
        for point_index in LIMB_POINTS:
            point = _pose_point(points, scores, point_index, LIMB_CONF)
            if point is not None:
                limb_points.append(point)
        poses.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "shoulder": shoulder,
                "limb_points": limb_points,
            }
        )
    return poses


def _pose_point(points, scores, index: int, minimum: float):
    if index >= len(points) or float(scores[index]) < minimum:
        return None
    x, y = float(points[index][0]), float(points[index][1])
    if x <= 0 and y <= 0:
        return None
    return x, y


def _public_box(box: dict, width: int, height: int) -> dict:
    return {
        "x1": box["x1"] / width,
        "y1": box["y1"] / height,
        "x2": box["x2"] / width,
        "y2": box["y2"] / height,
        "name": box["name"],
        "label": LABELS.get(box["name"], box["name"]),
    }


def _note_time(video_time: float) -> None:
    global _last_time, _layout, _layout_seen, _stable_since, _front_since
    if _last_time is not None and abs(video_time - _last_time) > 1.5:
        _layout = None
        _layout_seen = None
        _stable_since = None
        _front_since = None
    _last_time = video_time


def _observe_startup(details: list[dict], video_time: float) -> None:
    global _layout, _layout_seen, _stable_since, _fixed_box, _fixed_terminals, _box_updated_at, _passed
    for item in details:
        if item["name"] in _start:
            _start[item["name"]] = True
    if not all(_start.values()):
        return
    layout = _terminal_layout(details)
    if layout is None:
        if _layout_seen is not None and video_time - _layout_seen > 1.5:
            _layout = None
            _layout_seen = None
            _stable_since = None
        return
    _layout_seen = video_time
    if _layout is None or not _layout_stable(_layout, layout):
        _layout = layout
        _stable_since = video_time
        return
    if video_time - _stable_since >= STABLE_SECONDS:
        _fixed_box = dict(layout[0])
        _fixed_terminals = [dict(item) for item in layout[2]]
        _box_updated_at = video_time
        _passed[0] = True


def _refresh_transformer(details: list[dict], video_time: float) -> None:
    global _fixed_box, _fixed_terminals, _box_updated_at
    if _fixed_box is None or _box_updated_at is None:
        return
    if video_time - _box_updated_at < UPDATE_SECONDS:
        return
    selected = _transformer_selection(details)
    if selected is None:
        return
    box, terminals = selected
    _fixed_box = box
    _fixed_terminals = [dict(item) for item in terminals]
    _box_updated_at = video_time


def _terminal_layout(details: list[dict]):
    selected = _transformer_selection(details)
    grounds = [item for item in details if item["name"] == "ground_terminal"]
    if selected is None or not grounds:
        return None
    box, terminals = selected
    centers = sorted(
        (((item["x1"] + item["x2"]) / 2, (item["y1"] + item["y2"]) / 2) for item in grounds),
        key=lambda point: (point[0], point[1]),
    )
    return box, centers, terminals


def _layout_stable(previous, current) -> bool:
    old_box, old_grounds = previous[0], previous[1]
    new_box, new_grounds = current[0], current[1]
    if len(old_grounds) != len(new_grounds):
        return False
    width = max(old_box["x2"] - old_box["x1"], 1)
    height = max(old_box["y2"] - old_box["y1"], 1)
    limit_x = max(width * 0.12, 12)
    limit_y = max(height * 0.5, width * 0.06, 12)
    for key in ("x1", "y1", "x2", "y2"):
        limit = limit_x if key.startswith("x") else limit_y
        if abs(old_box[key] - new_box[key]) > limit:
            return False
    for old, new in zip(old_grounds, new_grounds):
        if abs(old[0] - new[0]) > limit_x or abs(old[1] - new[1]) > limit_y:
            return False
    return True


def _transformer_box(details: list[dict]) -> dict | None:
    selected = _transformer_selection(details)
    if selected is None:
        return None
    return selected[0]


def _transformer_selection(details: list[dict]):
    terminals = [item for item in details if item["name"] == "terminal"]
    if len(terminals) < 3:
        return None
    best = None
    best_score = 1e9
    for combo in itertools.combinations(terminals, 3):
        centers_y = [((item["y1"] + item["y2"]) / 2) for item in combo]
        centers_x = [((item["x1"] + item["x2"]) / 2) for item in combo]
        y_spread = max(centers_y) - min(centers_y)
        x_spread = max(centers_x) - min(centers_x)
        score = y_spread / max(x_spread, 1)
        if score < best_score:
            best_score = score
            best = combo
    box = {
        "x1": min(item["x1"] for item in best),
        "y1": min(item["y1"] for item in best),
        "x2": max(item["x2"] for item in best),
        "y2": max(item["y2"] for item in best),
    }
    return box, best


def _terminal_visible(saved: dict, current: dict) -> bool:
    saved_x = (saved["x1"] + saved["x2"]) / 2
    saved_y = (saved["y1"] + saved["y2"]) / 2
    current_x = (current["x1"] + current["x2"]) / 2
    current_y = (current["y1"] + current["y2"]) / 2
    width = max(saved["x2"] - saved["x1"], 1)
    height = max(saved["y2"] - saved["y1"], 1)
    return abs(saved_x - current_x) <= max(width, 24) and abs(saved_y - current_y) <= max(height * 2, 24)


def _terminal_occluded(details: list[dict]) -> bool:
    if not _fixed_terminals:
        return False
    visible = [item for item in details if item["name"] == "terminal"]
    for saved in _fixed_terminals:
        if not any(_terminal_visible(saved, item) for item in visible):
            return True
    return False


def _person_near_transformer(person: dict, transformer: dict) -> bool:
    width = max(transformer["x2"] - transformer["x1"], 1)
    height = max(transformer["y2"] - transformer["y1"], 1)
    left = transformer["x1"] - width * 0.2
    right = transformer["x2"] + width * 0.2
    top = transformer["y1"] - height * 4
    bottom = transformer["y2"] + height * 8
    return person["x1"] < right and person["x2"] > left and person["y1"] < bottom and person["y2"] > top


def _mark_sides(transformer: dict | None, people: list[dict], details: list[dict], video_time: float) -> None:
    global _front_since
    if transformer is None:
        return
    covered = _terminal_occluded(details) and any(_person_near_transformer(person, transformer) for person in people)
    if covered:
        if _front_since is None:
            _front_since = video_time
        elif video_time - _front_since >= FRONT_SECONDS:
            _sides["front"] = True
    else:
        _front_since = None
    height = max(transformer["y2"] - transformer["y1"], 1)
    reach_y = height * 3
    for person in people:
        center_x = (person["x1"] + person["x2"]) / 2
        center_y = (person["y1"] + person["y2"]) / 2
        near_row = transformer["y1"] - reach_y <= center_y <= transformer["y2"] + reach_y
        if center_x < transformer["x1"] and near_row:
            _sides["left"] = True
            continue
        if center_x > transformer["x2"] and near_row:
            _sides["right"] = True
            continue
        shoulder = person["shoulder"]
        if shoulder is None or not (transformer["x1"] <= shoulder[0] <= transformer["x2"]):
            continue
        foreground_y = transformer["y2"] + height
        limb_in_front = any(point[1] > foreground_y for point in person["limb_points"])
        if not limb_in_front and shoulder[1] <= foreground_y:
            _sides["back"] = True
