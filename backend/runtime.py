"""Process-wide services created at startup (see main.py lifespan)."""

from typing import Optional

from services.events import EventRecorder
from services.retention import RetentionScheduler
from vision.anomaly import AnomalyDetectorAdapter
from vision.camera_manager import CameraManager


class Runtime:
    recorder: Optional[EventRecorder] = None
    cameras: Optional[CameraManager] = None
    anomaly: Optional[AnomalyDetectorAdapter] = None
    retention: Optional[RetentionScheduler] = None


runtime = Runtime()
