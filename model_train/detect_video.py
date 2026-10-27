"""Play a chosen video and draw terminal detections.

Open a file after launch. Click or drag the progress bar to jump.
Space toggles play and pause. Esc closes the window.
"""

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
WEIGHTS = ROOT / "runs" / "terminal-yolo11s-p2-1280-8cls" / "weights" / "best.pt"
VIDEO_TYPES = [
    ("视频", "*.mp4 *.avi *.mkv *.mov *.wmv *.m4v *.flv"),
    ("所有文件", "*.*"),
]
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


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def draw_boxes(frame: np.ndarray, result) -> np.ndarray:
    canvas = frame.copy()
    if result.boxes is None:
        return canvas
    for box in result.boxes:
        x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
        cls_id = int(box.cls[0])
        name = result.names[cls_id]
        conf = float(box.conf[0])
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
    return canvas


class VideoDetector:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("端子视频检测")
        self.root.geometry("1100x760")
        self.root.minsize(800, 560)

        self.model = YOLO(str(WEIGHTS))
        self.capture: cv2.VideoCapture | None = None
        self.video_path: Path | None = None
        self.frame_count = 0
        self.frame_index = 0
        self.fps = 25.0
        self.playing = False
        self.scrubbing = False
        self.resume_after_scrub = False
        self.after_id: str | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.last_scrub = 0.0

        self._build()
        self.root.bind("<space>", lambda _event: self.toggle())
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.root.after(200, self.choose)

    def _build(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="选择视频", command=self.choose).pack(side="left")
        self.play_button = ttk.Button(bar, text="播放", command=self.toggle, state="disabled")
        self.play_button.pack(side="left", padx=(8, 0))
        self.name_label = ttk.Label(bar, text="尚未选择视频")
        self.name_label.pack(side="left", padx=(12, 0))

        self.view = tk.Label(self.root, bg="#111111", fg="#dddddd", text="请选择要检测的视频")
        self.view.pack(fill="both", expand=True, padx=10, pady=6)

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.time_label = ttk.Label(bottom, text="00:00", width=8)
        self.time_label.pack(side="left")
        self.duration_label = ttk.Label(bottom, text="00:00", width=8)
        self.duration_label.pack(side="right")
        self.bar = tk.Canvas(bottom, height=18, bg="#2b2b2b", highlightthickness=0, cursor="hand2")
        self.bar.pack(side="left", fill="x", expand=True, padx=8)
        self.bar.bind("<Button-1>", self.on_scrub_start)
        self.bar.bind("<B1-Motion>", self.on_scrub_move)
        self.bar.bind("<ButtonRelease-1>", self.on_scrub_end)
        self.bar.bind("<Configure>", lambda _event: self.draw_bar())

    def choose(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择要检测的视频",
            initialdir=str(ROOT),
            filetypes=VIDEO_TYPES,
        )
        if not selected:
            return
        self.open_video(Path(selected))

    def open_video(self, path: Path) -> None:
        self.pause()
        if self.capture is not None:
            self.capture.release()
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            self.name_label.config(text=f"无法打开: {path.name}")
            return
        self.capture = capture
        self.video_path = path
        self.frame_count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1)
        self.fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0) or 25.0
        self.frame_index = 0
        self.name_label.config(text=path.name)
        self.duration_label.config(text=format_time(self.frame_count / self.fps))
        self.play_button.config(state="normal", text="播放")
        self.show_frame(0)

    def show_frame(self, index: int) -> None:
        if self.capture is None:
            return
        index = min(max(0, index), self.frame_count - 1)
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return
        result = self.model.predict(frame, imgsz=1280, conf=0.25, device=0, verbose=False)[0]
        shown = self.fit(draw_boxes(frame, result))
        rgb = cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.view.config(image=self.photo, text="")
        self.frame_index = index
        self.time_label.config(text=format_time(index / self.fps))
        self.draw_bar()

    def fit(self, frame: np.ndarray) -> np.ndarray:
        max_width = max(320, self.view.winfo_width() - 4)
        max_height = max(240, self.view.winfo_height() - 4)
        height, width = frame.shape[:2]
        scale = min(max_width / width, max_height / height)
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)

    def draw_bar(self) -> None:
        width = max(1, self.bar.winfo_width())
        height = max(1, self.bar.winfo_height())
        fraction = 0.0 if self.frame_count <= 1 else self.frame_index / (self.frame_count - 1)
        played = int(width * fraction)
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, width, height, fill="#2b2b2b", outline="")
        self.bar.create_rectangle(0, 6, width, height - 6, fill="#4b4b4b", outline="")
        self.bar.create_rectangle(0, 6, played, height - 6, fill="#3b82f6", outline="")
        self.bar.create_oval(played - 7, 2, played + 7, height - 2, fill="#ffffff", outline="")

    def index_at(self, x: int) -> int:
        width = max(1, self.bar.winfo_width())
        fraction = min(max(x / width, 0.0), 1.0)
        return int(round(fraction * (self.frame_count - 1)))

    def on_scrub_start(self, event: tk.Event) -> None:
        if self.capture is None:
            return
        self.scrubbing = True
        self.resume_after_scrub = self.playing
        self.pause()
        self.show_frame(self.index_at(event.x))

    def on_scrub_move(self, event: tk.Event) -> None:
        if not self.scrubbing or self.capture is None:
            return
        now = time.perf_counter()
        if now - self.last_scrub < 0.08:
            return
        self.last_scrub = now
        self.show_frame(self.index_at(event.x))

    def on_scrub_end(self, event: tk.Event) -> None:
        if not self.scrubbing or self.capture is None:
            return
        self.show_frame(self.index_at(event.x))
        self.scrubbing = False
        if self.resume_after_scrub:
            self.play()

    def toggle(self) -> None:
        if self.capture is None:
            return
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self.capture is None or self.playing:
            return
        if self.frame_index >= self.frame_count - 1:
            self.show_frame(0)
        self.playing = True
        self.play_button.config(text="暂停")
        self.tick()

    def pause(self) -> None:
        self.playing = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        if self.capture is not None:
            self.play_button.config(text="播放")

    def tick(self) -> None:
        if not self.playing or self.capture is None:
            return
        nxt = self.frame_index + 1
        if nxt >= self.frame_count:
            self.pause()
            return
        started = time.perf_counter()
        self.show_frame(nxt)
        spent = time.perf_counter() - started
        delay = max(1, int(1000 / self.fps - spent * 1000))
        self.after_id = self.root.after(delay, self.tick)


def main() -> None:
    if not WEIGHTS.is_file():
        raise SystemExit(f"没有找到模型: {WEIGHTS}")
    root = tk.Tk()
    VideoDetector(root)
    root.mainloop()


if __name__ == "__main__":
    main()
