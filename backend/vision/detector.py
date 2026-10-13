"""
Person detector boundary.

The production implementation wraps the YOLO + ByteTrack pipeline used by the existing
entrance counter (viahind-person-counter/person_counter.py). Weights are never downloaded:
PERSON_MODEL_PATH must point at an existing local checkpoint (e.g. yolo11n.pt). When it is
not configured, cameras still stream but no entry/exit events are produced, and the UI says so.
"""

import logging
import os
from typing import List, Optional, Protocol, Tuple

from config import settings
from vision.line_crossing import Detection

logger = logging.getLogger("viahind.detector")

PERSON_CLASS_ID = 0  # "person" in COCO
# ByteTrack associates low-score boxes in its second stage, so the model runs with a low
# threshold and the operator's minimum confidence is applied later by LineCrossingCounter.
MODEL_CONF_FLOOR = 0.1


class PersonDetector(Protocol):
    def track(self, frame) -> List[Detection]:
        """Detect people in a BGR frame and return tracked detections (track IDs may be None)."""

    def reset(self) -> None:
        """Forget all tracks (after a disconnection or when a new session starts)."""


class YoloPersonTracker:
    """YOLO person detection with ByteTrack tracking; one instance per camera (tracker state is per instance)."""

    def __init__(self, model_path: str, tracker_config: str = "bytetrack.yaml", device: str = "cpu"):
        from ultralytics import YOLO  # imported lazily: heavy, and optional for the rest of the app

        self.model = YOLO(model_path)
        self.tracker_config = tracker_config
        self.device = device
        # Warm up (first inference is slow) without touching tracker state.
        import numpy as np

        self.model.predict(np.zeros((480, 640, 3), dtype=np.uint8), device=device, verbose=False)

    def track(self, frame) -> List[Detection]:
        results = self.model.track(
            frame,
            persist=True,
            tracker=self.tracker_config,
            classes=[PERSON_CLASS_ID],
            conf=MODEL_CONF_FLOOR,
            device=self.device,
            verbose=False,
        )
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []
        xyxy = boxes.xyxy.cpu().numpy().tolist()
        confs = boxes.conf.cpu().numpy().tolist()
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(xyxy)
        return [Detection(track_id=i, box=tuple(b), confidence=float(c)) for b, c, i in zip(xyxy, confs, ids)]

    def reset(self) -> None:
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", None) or []:
            tracker.reset()


def detector_availability() -> Tuple[bool, str]:
    """Whether a person detector can be created, with a human-readable reason if not."""
    path = settings.PERSON_MODEL_PATH.strip()
    if not path:
        return False, "Person detection is not configured (PERSON_MODEL_PATH is empty)."
    if not os.path.isfile(path):
        return False, "Person model weights were not found at the configured PERSON_MODEL_PATH."
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        return False, "The ultralytics package is not installed."
    return True, "YOLO person detector with ByteTrack."


def create_person_detector() -> Optional[PersonDetector]:
    """Factory used by camera workers. Raises if the model cannot be loaded."""
    available, reason = detector_availability()
    if not available:
        logger.info("Person detector unavailable: %s", reason)
        return None
    return YoloPersonTracker(settings.PERSON_MODEL_PATH.strip(), settings.PERSON_TRACKER_CONFIG, settings.DETECTION_DEVICE)
