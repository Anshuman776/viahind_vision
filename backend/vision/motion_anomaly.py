"""
Weight-free fallback for the video anomaly detector: vigorous movement between people in close contact.

Used while no trained fight classifier is configured (VIDEO_ANOMALY_MODE=auto) or on request
(VIDEO_ANOMALY_MODE=motion). It does NOT recognise fights. It measures something simpler and
explainable, and reports it as "Vigorous movement between people":

1. Contact: two or more tracked people whose boxes are close (centre distance < 1.2 x the wider box)
   in the same frame. Requires person detection on the camera.
2. Motion: dense optical flow (Farneback) on downscaled frames. Motion intensity is the mean of the
   strongest 25% of flow magnitudes inside the people's combined region (so still parts of the body
   boxes do not dilute it). It must exceed an absolute threshold and twice the same measure elsewhere
   in the frame (to ignore camera shake and lighting changes).
3. A clip is positive when contact with strong local motion is present in at least half of its frame
   pairs. The adapter additionally requires consecutive positive clips before raising an alert.

Typical false positives: hugging, dancing, sports, children playing, crowded doorways. Every alert is
for human review.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

Box = Tuple[float, float, float, float]  # normalised x1, y1, x2, y2

FLOW_SIZE = 112
LABEL = "Vigorous movement between people"


def contact_region(boxes: Sequence[Box]) -> Optional[Tuple[Box, int]]:
    """Union box of the people in close contact, and how many there are."""
    group = set()
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ca = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
            cb = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            width = max(a[2] - a[0], b[2] - b[0])
            if width > 0 and np.hypot(ca[0] - cb[0], ca[1] - cb[1]) < 1.2 * width:
                group.update((i, j))
    if not group:
        return None
    sel = [boxes[k] for k in group]
    return (min(b[0] for b in sel), min(b[1] for b in sel), max(b[2] for b in sel), max(b[3] for b in sel)), len(group)


def _intensity(values: np.ndarray) -> float:
    """Mean of the top quarter of the values."""
    flat = values.ravel()
    if flat.size == 0:
        return 0.0
    k = max(1, flat.size // 4)
    return float(np.partition(flat, flat.size - k)[-k:].mean())


def _gray(frame: np.ndarray) -> np.ndarray:
    small = cv2.resize(frame, (FLOW_SIZE, FLOW_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small


def analyse_clip(frames: Sequence[np.ndarray], people: Sequence[Sequence[Box]], motion_threshold: float = 2.5) -> Dict:
    """Score one clip. `people[i]` are the normalised person boxes in `frames[i]`."""
    if len(frames) < 2 or len(people) != len(frames):
        return {"is_anomaly": False, "confidence_score": 0.0, "label": LABEL, "reason": "clip too short", "metrics": {}}
    grays = [_gray(f) for f in frames]
    positives = contacts = 0
    region_motion: List[float] = []
    max_people = 0
    for k in range(1, len(grays)):
        found = contact_region(list(people[k]))
        if found is None:
            continue
        contacts += 1
        (x1, y1, x2, y2), n = found
        max_people = max(max_people, n)
        flow = cv2.calcOpticalFlowFarneback(grays[k - 1], grays[k], None, 0.5, 3, 13, 3, 5, 1.1, 0)
        mag = np.linalg.norm(flow, axis=2)
        r = (slice(max(0, int(y1 * FLOW_SIZE)), max(1, int(np.ceil(y2 * FLOW_SIZE)))),
             slice(max(0, int(x1 * FLOW_SIZE)), max(1, int(np.ceil(x2 * FLOW_SIZE)))))
        inside = mag[r]
        if inside.size == 0:
            continue
        mask = np.ones_like(mag, dtype=bool)
        mask[r] = False
        background = _intensity(mag[mask]) if mask.any() else 0.0
        local = _intensity(inside)
        region_motion.append(local)
        if local >= motion_threshold and local >= 2.0 * background + 0.3:
            positives += 1
    pairs = len(grays) - 1
    positive_fraction = positives / pairs
    mean_motion = float(np.mean(region_motion)) if region_motion else 0.0
    confidence = 0.0
    if positives:
        confidence = min(1.0, positive_fraction * min(1.0, mean_motion / (2 * motion_threshold)) * 1.5)
    return {
        "is_anomaly": positive_fraction >= 0.5,
        "confidence_score": round(confidence, 3),
        "label": LABEL,
        "metrics": {
            "contact_fraction": round(contacts / pairs, 2),
            "strong_motion_fraction": round(positive_fraction, 2),
            "mean_motion_px": round(mean_motion, 2),
            "peak_motion_px": round(max(region_motion), 2) if region_motion else 0.0,
            "people_in_contact": max_people,
            "motion_threshold_px": motion_threshold,
        },
    }
