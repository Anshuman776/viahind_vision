"""
VIAHIND-FightClassifier-MobileNetV3: a clip-level violence / physical-altercation classifier.

Architecture
    16 RGB frames (224x224) -> MobileNetV3-Small appearance stream (576-d per frame)
    + frame-difference images -> second MobileNetV3-Small motion stream (576-d per frame)
    -> 1-layer GRU (256) -> linear -> probability of "altercation"

Training (python manage.py train-fight-model --data <dir>)
    <dir>/<positive class>/*.mp4  and  <dir>/<negative class>/*.mp4
    Positive folder names: fight, fights, violence, violent. Negative: nonfight, non_fight, noviolence,
    nonviolence, normal. The RWF-2000 and Hockey Fight datasets use these layouts. Use footage you are
    licensed to use. A stratified hold-out split measures accuracy, precision, recall and F1; the
    decision threshold is chosen on the hold-out set.

Artifacts (written to MODEL_DIR/video/)
    <name>.pt    weights only (loaded with torch.load(weights_only=True): no pickled code is executed)
    <name>.json  metadata: version, clip length, input size, threshold, hold-out metrics, data summary
    The SHA-256 of the .pt file is stored in the metadata and verified before loading.

A classifier output is a probability for human review, never proof of an altercation.
"""

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger("viahind.fight_model")

CLIP_LENGTH = 16
INPUT_SIZE = 224
MODEL_NAME = "VIAHIND-FightClassifier-MobileNetV3"
POSITIVE_DIRS = {"fight", "fights", "violence", "violent"}
NEGATIVE_DIRS = {"nonfight", "non_fight", "nonfights", "noviolence", "nonviolence", "non_violence", "normal"}
VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".mpg", ".mpeg"}
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _torch():
    import torch
    import torch.nn as nn

    return torch, nn


def build_model(pretrained_backbone: bool = False):
    """Construct the network. ImageNet backbone weights are only downloaded when explicitly requested
    (training with --pretrained-backbone); inference always loads a local checkpoint."""
    torch, nn = _torch()
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

    class FightClassifier(nn.Module):
        """Two streams over the same 16-frame clip:
        - appearance: each RGB frame through MobileNetV3-Small (pretrained BatchNorm kept fixed when fine-tuning),
        - motion: each frame-to-frame difference image through a second MobileNetV3-Small (BatchNorm trainable,
          because difference images look nothing like ImageNet photos).
        Global pooling makes appearance features blind to where people move; the motion stream supplies that cue.
        Per-frame features (576 + 576) feed a GRU; its last state gives the clip logit."""

        def __init__(self):
            super().__init__()
            weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained_backbone else None
            self.features = mobilenet_v3_small(weights=weights).features
            self.motion_features = mobilenet_v3_small(weights=weights).features
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.gru = nn.GRU(input_size=576 * 2, hidden_size=256, batch_first=True)
            self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(256, 1))
            self.freeze_bn = pretrained_backbone
            for module in (self.motion_features, self.features):
                for m in module.modules():
                    if isinstance(m, nn.BatchNorm2d) and (module is self.motion_features or not pretrained_backbone):
                        m.momentum = 0.1

        def train(self, mode: bool = True):
            super().train(mode)
            if mode and self.freeze_bn:
                for m in self.features.modules():
                    if isinstance(m, nn.BatchNorm2d):
                        m.eval()
            return self

        def _encode(self, net, frames):
            b, t = frames.shape[:2]
            return self.pool(net(frames.flatten(0, 1))).flatten(1).view(b, t, -1)

        def forward(self, clips):  # clips: (B, T, 3, H, W) normalised
            appearance = self._encode(self.features, clips)
            diff = clips[:, 1:] - clips[:, :-1]
            diff = torch.cat([torch.zeros_like(diff[:, :1]), diff], dim=1)
            motion = self._encode(self.motion_features, diff)
            out, _ = self.gru(torch.cat([appearance, motion], dim=2))
            return self.head(out[:, -1]).squeeze(1)

    return FightClassifier()


# -- preprocessing -----------------------------------------------------------------------------------

def preprocess_clip(frames: Sequence[np.ndarray], clip_length: int = CLIP_LENGTH, size: int = INPUT_SIZE) -> np.ndarray:
    """BGR frames (any count >= 1) -> float32 array (T, 3, size, size), ImageNet-normalised.
    Frames are sampled uniformly to clip_length."""
    if len(frames) == 0:
        raise ValueError("empty clip")
    idx = np.linspace(0, len(frames) - 1, clip_length).round().astype(int)
    out = np.empty((clip_length, 3, size, size), dtype=np.float32)
    for i, j in enumerate(idx):
        f = frames[j]
        if f.ndim != 3 or f.shape[2] != 3:
            raise ValueError("frames must be HxWx3 BGR images")
        if f.shape[0] != size or f.shape[1] != size:
            f = cv2.resize(f, (size, size), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        out[i] = ((rgb - MEAN) / STD).transpose(2, 0, 1)
    return out


def read_video_clip(path: Path, clip_length: int = CLIP_LENGTH, size: int = INPUT_SIZE, max_frames: int = 300,
                    rng: Optional[random.Random] = None) -> Optional[np.ndarray]:
    """Read up to max_frames frames, pick a random (training) or central (rng=None) window."""
    cap = cv2.VideoCapture(str(path))
    frames: List[np.ndarray] = []
    try:
        while len(frames) < max_frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frames.append(cv2.resize(frame, (size, size), interpolation=cv2.INTER_AREA))
    finally:
        cap.release()
    if len(frames) < 2:
        return None
    window = min(len(frames), clip_length * 4)
    start = rng.randint(0, len(frames) - window) if rng else (len(frames) - window) // 2
    clip = preprocess_clip(frames[start:start + window], clip_length, size)
    if rng and rng.random() < 0.5:
        clip = clip[:, :, :, ::-1].copy()  # horizontal flip augmentation
    return clip


def find_dataset(root: Path) -> List[Tuple[Path, int]]:
    """All labelled videos under root (any depth), from folder names."""
    items: List[Tuple[Path, int]] = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in VIDEO_EXT or not path.is_file():
            continue
        parts = [p.lower() for p in path.relative_to(root).parts[:-1]]
        if any(p in POSITIVE_DIRS for p in parts):
            items.append((path, 1))
        elif any(p in NEGATIVE_DIRS for p in parts):
            items.append((path, 0))
    return items


# -- metrics -------------------------------------------------------------------------------------------

def binary_metrics(labels: Sequence[int], probs: Sequence[float], threshold: float) -> Dict[str, float]:
    tp = sum(1 for y, p in zip(labels, probs) if y == 1 and p >= threshold)
    fp = sum(1 for y, p in zip(labels, probs) if y == 0 and p >= threshold)
    fn = sum(1 for y, p in zip(labels, probs) if y == 1 and p < threshold)
    tn = sum(1 for y, p in zip(labels, probs) if y == 0 and p < threshold)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    n = len(labels) or 1
    return {"accuracy": round((tp + tn) / n, 4), "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "true_positives": tp, "false_positives": fp, "false_negatives": fn, "true_negatives": tn, "threshold": round(threshold, 3)}


def choose_threshold(labels: Sequence[int], probs: Sequence[float]) -> float:
    """Best-F1 threshold on the hold-out set, never below 0.5 (prefer fewer false alarms)."""
    best_t, best_f1 = 0.75, -1.0
    for t in np.arange(0.5, 0.96, 0.05):
        f1 = binary_metrics(labels, probs, float(t))["f1"]
        if f1 > best_f1 + 1e-9:
            best_t, best_f1 = float(t), f1
    return round(best_t, 2)


# -- artifacts -----------------------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LoadedModel:
    model: object
    meta: dict
    path: Path


def load_checkpoint(weights_path: Path, device: str = "cpu", expected_sha256: Optional[str] = None) -> LoadedModel:
    """Load weights safely: metadata JSON next to the weights, hash verified, weights_only=True."""
    torch, _ = _torch()
    weights_path = Path(weights_path)
    meta_path = weights_path.with_suffix(".json")
    if not weights_path.is_file() or not meta_path.is_file():
        raise FileNotFoundError("Fight model weights or their .json metadata were not found.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    digest = sha256_file(weights_path)
    for expected in (meta.get("sha256"), expected_sha256):
        if expected and expected != digest:
            raise ValueError("Fight model weights failed their integrity check (SHA-256 mismatch).")
    if meta.get("model_name") != MODEL_NAME:
        raise ValueError("The checkpoint is not a VIAHIND fight classifier.")
    model = build_model(pretrained_backbone=False)
    state = torch.load(weights_path, map_location=device, weights_only=True)
    model.load_state_dict(state)
    model.to(device).eval()
    return LoadedModel(model, meta, weights_path)


def predict_probability(loaded: LoadedModel, frames: Sequence[np.ndarray], device: str = "cpu") -> float:
    torch, _ = _torch()
    clip = preprocess_clip(frames, int(loaded.meta.get("clip_length", CLIP_LENGTH)), int(loaded.meta.get("input_size", INPUT_SIZE)))
    with torch.inference_mode():
        logit = loaded.model(torch.from_numpy(clip).unsqueeze(0).to(device))
        return float(torch.sigmoid(logit)[0])


# -- training ------------------------------------------------------------------------------------------

def official_split(root: Path, items: List[Tuple[Path, int]]) -> Optional[Tuple[list, list]]:
    """Use the dataset's own split when it has train/ and val|validation|test/ folders (RWF-2000 layout)."""
    train_names, val_names = {"train", "training"}, {"val", "valid", "validation", "test"}
    tr, va = [], []
    for path, y in items:
        parts = {q.lower() for q in path.relative_to(root).parts[:-1]}
        if parts & val_names:
            va.append((path, y))
        elif parts & train_names:
            tr.append((path, y))
    if tr and va and {y for _, y in tr} == {0, 1} and {y for _, y in va} == {0, 1}:
        return tr, va
    return None


class ClipDataset:
    """Decodes one clip per item (module-level so DataLoader workers can use it on Windows)."""

    def __init__(self, items: List[Tuple[Path, int]], training: bool, seed: int = 7):
        self.items, self.training, self.seed = items, training, seed

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, idx: int):
        path, y = self.items[idx]
        rng = random.Random() if self.training else None
        clip = read_video_clip(path, rng=rng)
        if clip is None:
            return np.zeros((CLIP_LENGTH, 3, INPUT_SIZE, INPUT_SIZE), np.float32), np.float32(y), np.float32(0)
        if self.training:
            clip = clip * np.float32(random.uniform(0.85, 1.15)) + np.float32(random.uniform(-0.15, 0.15))  # brightness/contrast jitter
        return clip.astype(np.float32), np.float32(y), np.float32(1)


def train(
    data_dir: Path,
    out_dir: Path,
    epochs: int = 8,
    batch_size: int = 4,
    lr: float = 3e-4,
    val_fraction: float = 0.2,
    pretrained_backbone: bool = False,
    device: str = "cpu",
    seed: int = 7,
    limit: Optional[int] = None,
    log: Callable[[str], None] = print,
    workers: int = 0,
) -> dict:
    torch, nn = _torch()
    from torch.utils.data import DataLoader

    data_dir, out_dir = Path(data_dir), Path(out_dir)
    if device.startswith("cuda") and not torch.cuda.is_available():
        log("CUDA is not available; training on the CPU.")
        device = "cpu"
    items = find_dataset(data_dir)
    rng = random.Random(seed)
    torch.manual_seed(seed)
    split = official_split(data_dir, items)
    if split:
        tr, val = split
        if limit:
            rng.shuffle(tr)
            rng.shuffle(val)
            tr, val = tr[:limit], val[: max(4, limit // 4)]
        log("Using the dataset's own train / validation split.")
    else:
        if limit:
            rng.shuffle(items)
            items = items[:limit]
        pos = [i for i in items if i[1] == 1]
        neg = [i for i in items if i[1] == 0]
        if len(pos) < 2 or len(neg) < 2:
            raise ValueError(f"Need at least 2 videos per class; found {len(pos)} positive and {len(neg)} negative under {data_dir}.")
        rng.shuffle(pos)
        rng.shuffle(neg)
        n_val_pos, n_val_neg = max(1, int(len(pos) * val_fraction)), max(1, int(len(neg) * val_fraction))
        val = pos[:n_val_pos] + neg[:n_val_neg]
        tr = pos[n_val_pos:] + neg[n_val_neg:]
    n_pos = sum(y for _, y in tr)
    if n_pos == 0 or n_pos == len(tr):
        raise ValueError("The training split must contain both classes.")
    log(f"Training on {len(tr)} videos ({n_pos} positive), validating on {len(val)} (device {device}).")

    use_amp = device.startswith("cuda")
    loader_args = {"num_workers": workers, "pin_memory": use_amp, "persistent_workers": workers > 0}
    train_loader = DataLoader(ClipDataset(tr, True, seed), batch_size=batch_size, shuffle=True, drop_last=len(tr) > batch_size, **loader_args)
    val_loader = DataLoader(ClipDataset(val, False, seed), batch_size=batch_size, shuffle=False, **loader_args)

    model = build_model(pretrained_backbone).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    steps = max(1, epochs * max(1, len(train_loader)))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.15)
    pos_weight = torch.tensor([(len(tr) - n_pos) / n_pos], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    def evaluate() -> Tuple[List[int], List[float]]:
        model.eval()
        labels, probs = [], []
        with torch.inference_mode(), torch.autocast("cuda", enabled=use_amp):
            for x, y, ok in val_loader:
                p = torch.sigmoid(model(x.to(device, non_blocking=True)).float()).cpu()
                for yi, pi, oi in zip(y.tolist(), p.tolist(), ok.tolist()):
                    if oi:
                        labels.append(int(yi))
                        probs.append(float(pi))
        return labels, probs

    best = None
    for epoch in range(1, epochs + 1):
        model.train()
        total, batches = 0.0, 0
        for x, y, ok in train_loader:
            keep = ok.bool()
            if not keep.any():
                continue
            x, y = x[keep].to(device, non_blocking=True), y[keep].to(device)
            with torch.autocast("cuda", enabled=use_amp):
                loss = loss_fn(model(x).float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += float(loss)
            batches += 1
        labels, probs = evaluate()
        m = binary_metrics(labels, probs, 0.5)
        log(f"epoch {epoch}/{epochs}: loss {total / max(1, batches):.4f}, validation accuracy {m['accuracy']:.3f}, "
            f"precision {m['precision']:.3f}, recall {m['recall']:.3f}, F1 {m['f1']:.3f}")
        if best is None or m["f1"] > best[0] or (m["f1"] == best[0] and m["accuracy"] > best[1]):
            best = (m["f1"], m["accuracy"], {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}, labels, probs, epoch)

    _, _, state, labels, probs, best_epoch = best
    threshold = choose_threshold(labels, probs)
    metrics = binary_metrics(labels, probs, threshold)
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = out_dir / f"fight_classifier_{version}.pt"
    torch.save(state, weights)
    meta = {
        "model_name": MODEL_NAME, "version": version, "clip_length": CLIP_LENGTH, "input_size": INPUT_SIZE,
        "threshold": threshold, "holdout_metrics": metrics, "pretrained_backbone": pretrained_backbone,
        "data": {"root": data_dir.name, "train_videos": len(tr), "holdout_videos": len(val),
                 "positive_train": n_pos, "official_split": bool(split)},
        "best_epoch": best_epoch, "epochs": epochs, "device": device,
        "trained_at": datetime.now(timezone.utc).isoformat(), "sha256": sha256_file(weights),
    }
    weights.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log(f"Saved {weights.name} (best epoch {best_epoch}): validation {metrics}.")
    return {"weights": str(weights), **meta}
