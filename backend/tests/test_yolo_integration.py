"""
Opt-in end-to-end test with the real YOLO + ByteTrack detector.

    VV_TEST_MODEL_PATH=C:/path/to/yolo11n.pt python -m pytest tests/test_yolo_integration.py

Builds a synthetic clip by moving a person cropped from Ultralytics' bundled sample image
(bus.jpg) down across an entrance line, then back up, and checks one entry and one exit
are recorded. No real residents' footage is needed. Skipped when weights are not provided.
"""

import os
import time
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select

import db
from models.entities import DetectionEvent, Visit
from services.events import EventRecorder
from vision.camera_worker import CameraSpec, CameraWorker
from vision.detector import YoloPersonTracker
from vision.line_crossing import CrossingParams, LineConfig

MODEL = os.getenv("VV_TEST_MODEL_PATH", "")
pytestmark = pytest.mark.skipif(not (MODEL and Path(MODEL).is_file()), reason="set VV_TEST_MODEL_PATH to run")


def person_crop(model_path):
    import cv2
    import ultralytics

    image = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
    detector = YoloPersonTracker(model_path)
    people = [d for d in detector.track(image) if d.confidence > 0.6]
    x1, y1, x2, y2 = (int(v) for v in max(people, key=lambda d: d.confidence).box)
    crop = image[y1:y2, x1:x2]
    scale = 220 / crop.shape[0]
    return cv2.resize(crop, (int(crop.shape[1] * scale), 220))


def synthetic_frames(crop, ys):
    h, w = crop.shape[:2]
    for y in ys:
        frame = np.full((480, 640, 3), (120, 125, 130), dtype=np.uint8)
        top = int(y - h / 2)
        frame[max(0, top):top + h, 260:260 + w] = crop[max(0, -top):h - max(0, top + h - 480)]
        yield frame


def test_real_detector_records_entry_then_exit(camera, snapshot_dir):
    crop = person_crop(MODEL)
    params = CrossingParams(min_confidence=0.4, cooldown_seconds=0.0, track_timeout_seconds=30, min_track_hits=3, min_side_frames=2, anchor="center")
    spec = CameraSpec(id=camera, name="Synthetic doorway", source_type="browser", source=None, line=LineConfig(0.05, 0.5, 0.95, 0.5))
    worker = CameraWorker(spec, lambda: params, lambda: YoloPersonTracker(MODEL), EventRecorder(), detection_max_fps=1000)
    worker.start()
    try:
        down = list(range(110, 380, 12))
        for frame in synthetic_frames(crop, down + [380] * 5 + down[::-1]):
            worker.push_frame(frame)
            time.sleep(0.25)  # give CPU inference time to consume each frame (the worker drops stale frames)
        deadline = time.time() + 10
        while time.time() < deadline and worker.events_recorded < 2:
            time.sleep(0.1)
    finally:
        worker.stop()

    with db.session_scope() as s:
        kinds = [e.event_type for e in s.scalars(select(DetectionEvent).order_by(DetectionEvent.occurred_at))]
        assert kinds == ["entry", "exit"]
        visit = s.scalar(select(Visit))
        assert visit.status == "exited" and visit.match_method == "tracker"
