"""Browse detections on images under model_train/photo.

Keys: a previous, d next, esc quit.
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
PHOTO_DIR = ROOT / "photo"
WEIGHTS = ROOT / "runs" / "terminal-yolo11s-p2-1280-8cls" / "weights" / "best.pt"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WINDOW = "端子检测"
COLORS = (
    (80, 80, 255),
    (0, 165, 255),
    (0, 200, 80),
    (255, 160, 0),
    (255, 80, 180),
    (0, 255, 255),
    (255, 255, 0),
    (180, 105, 255),
)
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")


def list_images() -> list[Path]:
    files = [path for path in PHOTO_DIR.rglob("*") if path.suffix.lower() in IMAGE_EXTS]
    return sorted(files, key=lambda path: str(path).lower())


def fit_screen(image: np.ndarray, max_width: int = 1600, max_height: int = 900) -> np.ndarray:
    height, width = image.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return image
    size = (int(width * scale), int(height * scale))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def draw_text(image: np.ndarray, lines: list[str]) -> np.ndarray:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    canvas = Image.fromarray(rgb)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(FONT_PATH), 28) if FONT_PATH.is_file() else ImageFont.load_default()
    y = 12
    for line in lines:
        box = draw.textbbox((16, y), line, font=font)
        draw.rectangle((box[0] - 6, box[1] - 4, box[2] + 6, box[3] + 4), fill=(0, 0, 0))
        draw.text((16, y), line, font=font, fill=(255, 255, 255))
        y = box[3] + 10
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def annotate(image: np.ndarray, result, index: int, total: int, path: Path, note: str = "") -> np.ndarray:
    canvas = image.copy()
    names = result.names
    counts: dict[str, int] = {}
    if result.boxes is not None:
        for box in result.boxes:
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            name = names[cls_id]
            counts[name] = counts.get(name, 0) + 1
            color = COLORS[cls_id % len(COLORS)]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                canvas,
                f"{name} {conf:.2f}",
                (x1, max(20, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )
    shown = fit_screen(canvas)
    summary = "、".join(f"{name} {count}" for name, count in counts.items()) or "未检测到目标"
    lines = [
        f"{index + 1}/{total}  {path.relative_to(PHOTO_DIR)}",
        summary,
        "A 上一张    D 下一张    Esc 退出",
    ]
    if note:
        lines.append(note)
    return draw_text(shown, lines)


def main() -> None:
    images = list_images()
    if not images:
        raise SystemExit(f"没有找到图片: {PHOTO_DIR}")
    if not WEIGHTS.is_file():
        raise SystemExit(f"没有找到模型: {WEIGHTS}")

    model = YOLO(str(WEIGHTS))
    cache: dict[Path, object] = {}
    index = 0
    note = ""
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    while True:
        path = images[index]
        if path not in cache:
            cache[path] = model.predict(str(path), imgsz=1280, conf=0.25, device=0, verbose=False)[0]
        frame = annotate(cv2.imread(str(path)), cache[path], index, len(images), path, note)
        cv2.imshow(WINDOW, frame)
        key = cv2.waitKey(0) & 0xFF
        note = ""
        if key == 27:
            break
        if key in (ord("a"), ord("A")):
            if index == 0:
                note = "已经是第一张"
            else:
                index -= 1
        elif key in (ord("d"), ord("D")):
            if index == len(images) - 1:
                note = "已经是最后一张"
            else:
                index += 1

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
