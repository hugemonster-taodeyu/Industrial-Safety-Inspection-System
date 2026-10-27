"""Train YOLO11s-P2 on the transformer terminal dataset.

Run later with the conda environment. This file does not train on import.

    conda activate terminal-yolo
    python model_train/train.py

Ultralytics 8.4 has no published yolo11s-p2.pt. The script builds
model_train/yolo11-p2.yaml at scale s and copies matching layers from yolo11s.pt.
The first run downloads yolo11s.pt. Results go to model_train/runs.
"""

from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "dataset" / "data.yaml"
RUNS = ROOT / "runs"
# The s in the filename selects scale s. The file on disk is yolo11-p2.yaml.
MODEL_CFG = ROOT / "yolo11s-p2.yaml"
LOCAL_P2_WEIGHTS = ROOT / "yolo11s-p2.pt"
COCO_WEIGHTS = ROOT / "weights" / "yolo11s.pt"


def build_model() -> YOLO:
    """Return a YOLO11s-P2 model seeded from COCO weights where the layers match."""
    if LOCAL_P2_WEIGHTS.is_file():
        return YOLO(str(LOCAL_P2_WEIGHTS))
    if not COCO_WEIGHTS.is_file():
        raise FileNotFoundError(f"COCO weights not found: {COCO_WEIGHTS}")
    model = YOLO(str(MODEL_CFG))
    model.load(str(COCO_WEIGHTS))
    return model


def train() -> None:
    if not DATA.is_file():
        raise FileNotFoundError(f"Dataset config not found: {DATA}")

    model = build_model()
    # pretrained stays on so train() keeps the weights loaded above.
    # Passing pretrained=False would rebuild the P2 model from random initialization.
    model.train(
        data=str(DATA),
        imgsz=1280,
        epochs=150,
        patience=40,
        batch=4,
        device=0,
        optimizer="AdamW",
        lr0=0.001,
        cos_lr=True,
        hsv_h=0.0,
        hsv_s=0.25,
        hsv_v=0.25,
        mixup=0.0,
        copy_paste=0.0,
        mosaic=1.0,
        close_mosaic=20,
        scale=0.5,
        degrees=5.0,
        translate=0.08,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,
        amp=True,
        workers=4,
        project=str(RUNS),
        name="terminal-yolo11s-p2-1280-8cls",
        resume=False,
    )


if __name__ == "__main__":
    train()
