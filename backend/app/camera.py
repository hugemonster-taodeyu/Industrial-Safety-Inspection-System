import os
import subprocess
import threading
import time

_lock = threading.Lock()
_probe_lock = threading.Lock()
_frame: bytes | None = None
_connected = False
_source = ""
_device_index: int | None = None
_device_name = ""
_stream_url = ""
_width = 0
_height = 0
_thread: threading.Thread | None = None
_stop = threading.Event()
_ready = threading.Event()
_last_error = ""
_pnp_cache: list[dict] = []
_pnp_cached_at = 0.0


def last_error() -> str:
    with _lock:
        return _last_error


def _set_error(message: str) -> None:
    global _last_error
    with _lock:
        _last_error = message


def _pnp_cameras() -> list[dict]:
    global _pnp_cache, _pnp_cached_at
    now = time.time()
    if _pnp_cache and now - _pnp_cached_at < 8:
        return list(_pnp_cache)
    script = (
        "Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue "
        "| Select-Object Status,FriendlyName "
        "| ConvertTo-Json -Compress"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            errors="replace",
            timeout=15,
        ).strip()
    except Exception:
        return list(_pnp_cache)
    if not raw:
        _pnp_cache = []
        _pnp_cached_at = now
        return []
    import json

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    devices = []
    for item in data:
        name = (item.get("FriendlyName") or "").strip()
        if not name:
            continue
        ready = item.get("Status") == "OK"
        devices.append({"name": name, "ready": ready})
    _pnp_cache = devices
    _pnp_cached_at = now
    return list(devices)


def list_cameras() -> list[dict]:
    with _probe_lock:
        with _lock:
            current_index = _device_index if _connected and _source == "local" else None
            current_name = _device_name
        pnp = _pnp_cameras()
    unique = {}
    for item in pnp:
        current = unique.get(item["name"])
        if current is None or (item["ready"] and not current["ready"]):
            unique[item["name"]] = item
    ordered = [item for item in unique.values() if item["ready"]] + [item for item in unique.values() if not item["ready"]]
    devices = []
    for offset, item in enumerate(ordered):
        label = item["name"] if item["ready"] else f"{item['name']}（未就绪）"
        devices.append({"index": offset, "name": label, "ready": item["ready"], "kind": "local"})
    if current_index is not None and current_name and not any(current_name in item["name"] for item in devices):
        devices.insert(0, {"index": current_index, "name": current_name, "ready": True, "kind": "local"})
    return devices


def _open_capture(source: str, index: int | None, name: str, url: str):
    import cv2

    if source == "network":
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(url)
        return cap
    attempts = []
    if index is not None:
        attempts.append((index, cv2.CAP_DSHOW))
    for target, backend in attempts:
        cap = cv2.VideoCapture(target, backend)
        if cap.isOpened():
            return cap
        cap.release()
    return None


def _capture_loop(source: str, index: int | None, name: str, url: str) -> None:
    global _frame, _connected, _last_error
    try:
        import cv2
    except Exception:
        _set_error("未安装 OpenCV，无法打开摄像头")
        with _lock:
            _connected = False
            _frame = None
        _ready.set()
        return
    with _probe_lock:
        cap = _open_capture(source, index, name, url)
    if cap is None or not cap.isOpened():
        if cap is not None:
            cap.release()
        if source == "network":
            _set_error("网络摄像头连接失败，请检查地址、账号密码和局域网")
        else:
            clean = name.replace("（未就绪）", "").strip() or "本机摄像头"
            _set_error(f"{clean}当前未就绪。请打开摄像头开关，并在 Windows 隐私设置里允许应用访问相机后再连接")
        with _lock:
            _connected = False
            _frame = None
        _ready.set()
        return
    while not _stop.is_set():
        ok, image = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        try:
            from .detect import draw_overlays, submit_frame

            submit_frame(image.copy())
            draw_overlays(image)
        except Exception:
            pass
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            continue
        with _lock:
            _connected = True
            _last_error = ""
            _frame = encoded.tobytes()
            _width = int(image.shape[1])
            _height = int(image.shape[0])
        if not _ready.is_set():
            _ready.set()
        time.sleep(0.05)
    cap.release()
    with _lock:
        _connected = False
        _frame = None


def disconnect_camera() -> None:
    global _thread, _device_index, _device_name, _stream_url, _source, _width, _height
    _stop.set()
    thread = _thread
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2)
    _thread = None
    with _lock:
        _frame = None
        _connected = False
        _source = ""
        _device_index = None
        _device_name = ""
        _stream_url = ""
        _width = 0
        _height = 0


def connect_camera(source: str, index: int | None = None, name: str = "", url: str = "") -> bool:
    global _thread, _device_index, _device_name, _stream_url, _source, _connected, _last_error
    disconnect_camera()
    _stop.clear()
    _ready.clear()
    _set_error("")
    with _lock:
        _source = source
        _device_index = index
        _device_name = name or (url if source == "network" else "摄像头")
        _stream_url = url
        _connected = False
        _frame = None
    _thread = threading.Thread(
        target=_capture_loop,
        args=(source, index, name, url),
        daemon=True,
    )
    _thread.start()
    _ready.wait(20 if source == "network" else 12)
    with _lock:
        if _connected:
            return True
    disconnect_camera()
    if not last_error():
        _set_error("摄像头连接失败")
    return False


def active_camera() -> dict:
    with _lock:
        return {
            "connected": _connected,
            "source": _source,
            "device_index": _device_index,
            "device_name": _device_name,
            "stream_url": _stream_url,
            "width": _width,
            "height": _height,
        }


def same_camera(source: str, index: int | None, url: str) -> bool:
    with _lock:
        if not _connected or _source != source:
            return False
        if source == "network":
            return _stream_url == url
        return _device_index == index


def mjpeg_frames():
    while True:
        with _lock:
            frame = _frame
            connected = _connected
        if connected and frame:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        else:
            time.sleep(0.3)
            continue
        time.sleep(0.05)
