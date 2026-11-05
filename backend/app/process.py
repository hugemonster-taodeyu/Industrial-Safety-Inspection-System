import itertools
import math
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
    "glove": "绝缘手套",
    "rod": "导电棒",
}

GLOVE_WEIGHTS = detect.MODELS / "glove.pt"
ROD_WEIGHTS = detect.MODELS / "rod.pt"
ELBOW_REACH = 0.5
ROD_SIDE_RATIO = 0.18
ROD_END_RATIO = 0.2
ROD_HOLD_SECONDS = 0.3
DISCHARGE_SECONDS = 5.0
CONNECTED_PHASES = ("connect_terminal_c", "connect_terminal_b", "connect_terminal_a")

_lock = threading.Lock()
_detail_model = None
_glove_model = None
_rod_model = None
_device = 0
_running = False
_sides = {"left": False, "right": False, "front": False, "back": False}
_parts = {name: False for name in WIRING_PARTS}
_start = {"terminal": False, "ground_terminal": False}
_passed = [False, False, False, False, False, False, False]
_hands = {"left": False, "right": False}
_rod_since = None
_discharge_since = None
_discharge_box = None
_discharge_terminals = None
_discharge_updated_at = None
_end_since = None
_end_seen_at = None
_end_parts = {name: False for name in WIRING_PARTS}
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
    global _sides, _parts, _start, _passed, _hands, _rod_since, _discharge_since, _discharge_box, _discharge_terminals, _discharge_updated_at
    global _end_since, _end_seen_at, _end_parts, _layout, _layout_seen, _stable_since
    global _fixed_box, _fixed_terminals, _box_updated_at, _last_time, _front_since
    _sides = {"left": False, "right": False, "front": False, "back": False}
    _parts = {name: False for name in WIRING_PARTS}
    _start = {"terminal": False, "ground_terminal": False}
    _passed = [False, False, False, False, False, False, False]
    _hands = {"left": False, "right": False}
    _rod_since = None
    _discharge_since = None
    _discharge_box = None
    _discharge_terminals = None
    _discharge_updated_at = None
    _end_since = None
    _end_seen_at = None
    _end_parts = {name: False for name in WIRING_PARTS}
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
            {"name": "佩戴手套", "passed": _passed[3], "hands": dict(_hands)},
            {"name": "拿起导电棒", "passed": _passed[4], "hands": dict(_hands)},
            {"name": "放电", "passed": _passed[5]},
            {"name": "结束", "passed": _passed[6], "parts": dict(_end_parts)},
        ],
        "boxes": boxes or [],
    }


def _ensure_glove() -> None:
    global _glove_model
    if _glove_model is not None:
        return
    from ultralytics import YOLO

    if not GLOVE_WEIGHTS.is_file():
        raise FileNotFoundError(f"未找到手套模型 {GLOVE_WEIGHTS}")
    _glove_model = YOLO(detect._model_file(GLOVE_WEIGHTS))


def _ensure_rod() -> None:
    global _rod_model
    if _rod_model is not None:
        return
    from ultralytics import YOLO

    if not ROD_WEIGHTS.is_file():
        raise FileNotFoundError(f"未找到导电棒模型 {ROD_WEIGHTS}")
    _rod_model = YOLO(detect._model_file(ROD_WEIGHTS))


def _ensure_detail() -> None:
    global _detail_model
    if _detail_model is not None:
        return
    from ultralytics import YOLO

    path = detect.MODELS / "terminal.pt"
    if not path.exists():
        raise FileNotFoundError("未找到变压器细节模型 terminal.pt")
    _detail_model = YOLO(detect._model_file(path))


def start_process() -> dict:
    global _running
    detect._ensure_models({4})
    if detect._pose_model is None:
        raise RuntimeError(detect._model_error or "姿态模型未就绪")
    _ensure_detail()
    _ensure_glove()
    _ensure_rod()
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
    poses = _poses(image) if step in (1, 3, 4, 5) else []
    gloves = _detect_gloves(image) if step in (3, 4) else []
    rod = _detect_rod(image) if step in (4, 5) else None
    for item in gloves:
        boxes.append(_public_box(item, width, height))
    if rod is not None:
        boxes.append(_public_box(_expand_rod(rod, width, height), width, height))
    if step != 5:
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
        elif step == 3:
            _observe_gloves(gloves, poses)
        elif step == 4:
            _observe_rod(gloves, rod, poses, video_time, width, height)
        elif step == 5:
            _observe_discharge(details, rod, poses, video_time, width, height)
        elif step == 6:
            _observe_finish(details, video_time)
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
    for xyxy, cls, conf in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy()):
        name = str(names.get(int(cls), ""))
        x1, y1, x2, y2 = [float(value) for value in xyxy]
        boxes.append({"name": name, "conf": float(conf), "x1": x1, "y1": y1, "x2": x2, "y2": y2})
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
                "left_elbow": detect._keypoint(points, scores, 7),
                "right_elbow": detect._keypoint(points, scores, 8),
                "left_wrist": detect._keypoint(points, scores, 9),
                "right_wrist": detect._keypoint(points, scores, 10),
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
    global _last_time, _layout, _layout_seen, _stable_since, _front_since, _rod_since, _discharge_since, _end_since, _end_seen_at, _end_parts
    if _last_time is not None and abs(video_time - _last_time) > 1.5:
        _layout = None
        _layout_seen = None
        _stable_since = None
        _front_since = None
        _rod_since = None
        _discharge_since = None
        _end_since = None
        _end_seen_at = None
        _end_parts = {name: False for name in WIRING_PARTS}
    _last_time = video_time


def _detect_gloves(image) -> list[dict]:
    result = _predict(_glove_model, image, imgsz=1280, conf=0.25)
    names = result.names or {}
    boxes = []
    if result.boxes is None:
        return boxes
    for xyxy, cls, conf in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy()):
        if str(names.get(int(cls), "")) != "glove":
            continue
        x1, y1, x2, y2 = [float(value) for value in xyxy]
        boxes.append({"name": "glove", "conf": float(conf), "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    boxes.sort(key=lambda item: item.get("conf", 0), reverse=True)
    return boxes[:2]


def _detect_rod(image) -> dict | None:
    result = _predict(_rod_model, image, imgsz=1280, conf=0.25)
    names = result.names or {}
    found = []
    if result.boxes is None:
        return None
    for xyxy, cls, conf in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy()):
        if str(names.get(int(cls), "")) != "rod":
            continue
        x1, y1, x2, y2 = [float(value) for value in xyxy]
        found.append({"name": "rod", "conf": float(conf), "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    if not found:
        return None
    return max(found, key=lambda item: item["conf"])


def _expand_rod(rod: dict, frame_width: int, frame_height: int) -> dict:
    width = max(rod["x2"] - rod["x1"], 1.0)
    height = max(rod["y2"] - rod["y1"], 1.0)
    long_side = max(width, height)
    side = ROD_SIDE_RATIO * long_side
    end = ROD_END_RATIO * long_side
    if width >= height:
        pad_x, pad_y = side + end, side
    else:
        pad_x, pad_y = side, side + end
    grown = dict(rod)
    grown["x1"] = max(0.0, rod["x1"] - pad_x)
    grown["y1"] = max(0.0, rod["y1"] - pad_y)
    grown["x2"] = min(float(frame_width - 1), rod["x2"] + pad_x)
    grown["y2"] = min(float(frame_height - 1), rod["y2"] + pad_y)
    return grown


def _point_inside(point: tuple[float, float], box: dict) -> bool:
    x, y = point
    return box["x1"] <= x <= box["x2"] and box["y1"] <= y <= box["y2"]


def _point_box_distance(point: tuple[float, float], box: dict) -> float:
    x, y = point
    dx = max(box["x1"] - x, 0.0, x - box["x2"])
    dy = max(box["y1"] - y, 0.0, y - box["y2"])
    return math.hypot(dx, dy)


def _gloved_hands(gloves: list[dict], poses: list[dict]) -> list[dict]:
    hands = []
    for person, pose in enumerate(poses):
        for side in ("left", "right"):
            wrist = pose.get(f"{side}_wrist")
            if wrist is None:
                continue
            elbow = pose.get(f"{side}_elbow")
            forearm = None
            if elbow is not None:
                forearm = math.hypot(elbow[0] - wrist[0], elbow[1] - wrist[1])
            hands.append({"person": person, "side": side, "elbow": elbow, "wrist": wrist, "forearm": forearm})
    occupancy = [0] * len(gloves)
    for hand in hands:
        for index, box in enumerate(gloves):
            if _point_inside(hand["wrist"], box):
                occupancy[index] += 1
    candidates = []
    for hand in hands:
        if hand["elbow"] is None or hand["forearm"] is None:
            continue
        for index, box in enumerate(gloves):
            if occupancy[index] != 1 or not _point_inside(hand["wrist"], box):
                continue
            distance = _point_box_distance(hand["elbow"], box)
            if distance > ELBOW_REACH * hand["forearm"]:
                continue
            candidates.append((distance, hand, index))
    worn_hands: list[dict] = []
    used_people: set[tuple[int, str]] = set()
    used_boxes: set[int] = set()
    for _distance, hand, index in sorted(candidates, key=lambda item: item[0]):
        key = (hand["person"], hand["side"])
        if key in used_people or index in used_boxes:
            continue
        used_people.add(key)
        used_boxes.add(index)
        worn_hands.append(hand)
    return worn_hands


def _worn_hands(gloves: list[dict], poses: list[dict]) -> set[tuple[int, str]]:
    return {(hand["person"], hand["side"]) for hand in _gloved_hands(gloves, poses)}


def _observe_gloves(gloves: list[dict], poses: list[dict]) -> None:
    global _hands, _passed
    worn = _worn_hands(gloves, poses)
    by_person: dict[int, set[str]] = {}
    for person, side in worn:
        by_person.setdefault(person, set()).add(side)
    chosen = max(by_person.values(), key=len) if by_person else set()
    _hands = {"left": "left" in chosen, "right": "right" in chosen}
    if _hands["left"] and _hands["right"]:
        _passed[3] = True


def _box_contains(outer: dict, inner: dict) -> bool:
    return outer["x1"] <= inner["x1"] and outer["y1"] <= inner["y1"] and outer["x2"] >= inner["x2"] and outer["y2"] >= inner["y2"]


def _holding_rod(gloves: list[dict], rod: dict | None, poses: list[dict], frame_width: int, frame_height: int) -> bool:
    if rod is None:
        return False
    area = _expand_rod(rod, frame_width, frame_height)
    by_person: dict[int, list[dict]] = {}
    for hand in _gloved_hands(gloves, poses):
        by_person.setdefault(hand["person"], []).append(hand)
    for person, hands in by_person.items():
        sides = {hand["side"] for hand in hands}
        if sides != {"left", "right"}:
            continue
        if _box_contains(rod, poses[person]):
            continue
        if any(_point_inside(hand["wrist"], area) for hand in hands):
            return True
    return False


def _observe_rod(gloves: list[dict], rod: dict | None, poses: list[dict], video_time: float, frame_width: int, frame_height: int) -> None:
    global _hands, _rod_since, _passed
    worn = _worn_hands(gloves, poses)
    by_person: dict[int, set[str]] = {}
    for person, side in worn:
        by_person.setdefault(person, set()).add(side)
    chosen = max(by_person.values(), key=len) if by_person else set()
    _hands = {"left": "left" in chosen, "right": "right" in chosen}
    if not _holding_rod(gloves, rod, poses, frame_width, frame_height):
        _rod_since = None
        return
    if _rod_since is None:
        _rod_since = video_time
    if video_time - _rod_since >= ROD_HOLD_SECONDS:
        _passed[4] = True


def _center_x(box: dict) -> float:
    return (box["x1"] + box["x2"]) / 2


def _union_box(items: list[dict]) -> dict:
    return {
        "x1": min(item["x1"] for item in items),
        "y1": min(item["y1"] for item in items),
        "x2": max(item["x2"] for item in items),
        "y2": max(item["y2"] for item in items),
    }


def _connected_region(details: list[dict]):
    chosen = []
    for name in CONNECTED_PHASES:
        matches = [item for item in details if item["name"] == name]
        if not matches:
            return None
        chosen.append(max(matches, key=lambda item: item.get("conf", 0)))
    left, middle, right = chosen
    if not _center_x(left) < _center_x(middle) < _center_x(right):
        return None
    return _union_box(chosen), chosen


def _phase_visible(saved: dict, current: dict) -> bool:
    if saved["name"] != current["name"]:
        return False
    saved_x = (saved["x1"] + saved["x2"]) / 2
    saved_y = (saved["y1"] + saved["y2"]) / 2
    current_x = (current["x1"] + current["x2"]) / 2
    current_y = (current["y1"] + current["y2"]) / 2
    width = max(saved["x2"] - saved["x1"], 1)
    height = max(saved["y2"] - saved["y1"], 1)
    return abs(saved_x - current_x) <= max(width, 24) and abs(saved_y - current_y) <= max(height * 2, 24)


def _region_stable(previous_box: dict, current_box: dict) -> bool:
    width = max(previous_box["x2"] - previous_box["x1"], 1)
    height = max(previous_box["y2"] - previous_box["y1"], 1)
    limit_x = max(width * 0.12, 12)
    limit_y = max(height * 0.5, width * 0.06, 12)
    for key in ("x1", "y1", "x2", "y2"):
        limit = limit_x if key.startswith("x") else limit_y
        if abs(previous_box[key] - current_box[key]) > limit:
            return False
    return True


def _phases_occluded(details: list[dict]) -> bool:
    if not _discharge_terminals:
        return False
    visible = [item for item in details if item["name"] in CONNECTED_PHASES]
    return any(not any(_phase_visible(saved, item) for item in visible) for saved in _discharge_terminals)


def _remember_discharge(box: dict, chosen: list[dict], video_time: float) -> None:
    global _discharge_box, _discharge_terminals, _discharge_updated_at
    _discharge_box = box
    _discharge_terminals = [dict(item) for item in chosen]
    _discharge_updated_at = video_time


def _update_discharge_region(details: list[dict], video_time: float) -> None:
    selected = _connected_region(details)
    was_occluded = _phases_occluded(details)
    if selected is None:
        return
    box, chosen = selected
    due = _discharge_updated_at is None or video_time - _discharge_updated_at >= UPDATE_SECONDS
    if _discharge_box is None or was_occluded or (_region_stable(_discharge_box, box) and due):
        _remember_discharge(box, chosen, video_time)


def _rod_ends(rod: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    mid_x = (rod["x1"] + rod["x2"]) / 2
    mid_y = (rod["y1"] + rod["y2"]) / 2
    if rod["x2"] - rod["x1"] >= rod["y2"] - rod["y1"]:
        return (rod["x1"], mid_y), (rod["x2"], mid_y)
    return (mid_x, rod["y1"]), (mid_x, rod["y2"])


def _person_anchor(person: dict) -> tuple[float, float]:
    wrist = person.get("left_wrist") or person.get("right_wrist")
    if wrist is not None:
        return wrist
    return ((person["x1"] + person["x2"]) / 2, (person["y1"] + person["y2"]) / 2)


def _nearest_person(rod: dict, poses: list[dict]) -> dict | None:
    if not poses:
        return None
    center = ((rod["x1"] + rod["x2"]) / 2, (rod["y1"] + rod["y2"]) / 2)
    return min(poses, key=lambda pose: _point_box_distance(center, pose))


def _discharge_contact(rod_area: dict, person: dict, region: dict, terminals: list[dict]) -> bool:
    anchor = _person_anchor(person)
    ends = _rod_ends(rod_area)
    near, far = sorted(ends, key=lambda point: math.hypot(point[0] - anchor[0], point[1] - anchor[1]))
    sizes = [max(item["x2"] - item["x1"], item["y2"] - item["y1"], 1) for item in terminals]
    reach = 0.75 * (sum(sizes) / len(sizes))
    far_distance = _point_box_distance(far, region)
    near_distance = _point_box_distance(near, region)
    return far_distance <= reach and far_distance <= near_distance


def _observe_discharge(details: list[dict], rod: dict | None, poses: list[dict], video_time: float, frame_width: int, frame_height: int) -> None:
    global _discharge_since, _passed
    _update_discharge_region(details, video_time)
    area = _expand_rod(rod, frame_width, frame_height) if rod is not None else None
    person = _nearest_person(area, poses) if area is not None else None
    contacting = (
        area is not None
        and person is not None
        and _discharge_box is not None
        and _discharge_terminals
        and _discharge_contact(area, person, _discharge_box, _discharge_terminals)
    )
    if not contacting:
        _discharge_since = None
        return
    if _discharge_since is None:
        _discharge_since = video_time
    if video_time - _discharge_since >= DISCHARGE_SECONDS:
        _passed[5] = True


def _observe_finish(details: list[dict], video_time: float) -> None:
    global _end_since, _end_seen_at, _end_parts, _passed
    present = {name: any(item["name"] == name for item in details) for name in WIRING_PARTS}
    if all(present.values()):
        if _end_since is None or (_end_seen_at is not None and video_time - _end_seen_at > 1.5):
            _end_since = video_time
            _end_parts = {name: False for name in WIRING_PARTS}
        _end_seen_at = video_time
        for name in WIRING_PARTS:
            _end_parts[name] = True
        if video_time - _end_since >= STABLE_SECONDS:
            _passed[6] = True
        return
    for name, seen in present.items():
        if seen:
            _end_parts[name] = True
    if _end_seen_at is not None and video_time - _end_seen_at > 1.5:
        _end_since = None
        _end_seen_at = None
        _end_parts = {name: False for name in WIRING_PARTS}


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
