"""
Integration boundary for the existing YOLO / fight anomaly-detection component.

CONNECTION POINT: edge-agent/fight_detector.py -> FightDetector.predict_clip(frame_sequence)

The existing component is loaded as-is; it is not retrained, rewritten or duplicated here.
At the time of integration, FightDetector.predict_clip() in this repository is a signature
placeholder that returns {"is_fight": False, ...} and holds no model object. Once the trained
model is wired into that method (or a different class is configured), this adapter starts
recording its real outputs; nothing else in the application needs to change.

Design rules:
- Disabled unless ANOMALY_DETECTION_ENABLED=True.
- Runs in its own thread with a bounded queue; clips are dropped (and counted) rather than
  ever blocking the camera or the person-tracking pipeline.
- Only outputs the model actually produced are recorded. No outputs are invented, and a
  failing model produces an error status, not alerts.
- Entry/exit tracking is independent of this adapter.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import cv2

from config import settings
from vision.edge_agent import load_edge_agent_module

logger = logging.getLogger("viahind.anomaly")

MODEL_ATTRIBUTES = ("model", "session", "net", "interpreter", "engine")


@dataclass(frozen=True)
class AnomalyResult:
    camera_id: str
    occurred_at: float
    label: str
    confidence: float
    model_name: str
    model_version: str
    raw_output: dict


class AnomalyDetectorAdapter:
    def __init__(
        self,
        on_event: Callable[[AnomalyResult], None],
        enabled: Optional[bool] = None,
        detector_factory: Optional[Callable[[], object]] = None,
        sample_every_n_frames: Optional[int] = None,
        clip_length: Optional[int] = None,
        threshold: Optional[float] = None,
        clip_size: int = 224,
    ):
        self.enabled = settings.ANOMALY_DETECTION_ENABLED if enabled is None else enabled
        self.on_event = on_event
        self.detector_factory = detector_factory or self._load_existing_detector
        self.sample_every = max(1, sample_every_n_frames or settings.ANOMALY_SAMPLE_EVERY_N_FRAMES)
        self.clip_length = max(1, clip_length or settings.ANOMALY_CLIP_LENGTH)
        self.threshold = settings.FIGHT_CONFIDENCE_THRESHOLD if threshold is None else threshold
        self.clip_size = clip_size

        self._detector = None
        self._status = "disabled" if not self.enabled else "not_initialized"
        self._message = "Anomaly detection is disabled (ANOMALY_DETECTION_ENABLED=False)." if not self.enabled else ""
        self._queue: "queue.Queue[tuple]" = queue.Queue(maxsize=2)
        self._buffers: Dict[str, List] = {}
        self._frame_counters: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.processed_clips = 0
        self.dropped_clips = 0
        self.failed_inferences = 0
        self.last_inference_at: Optional[float] = None

    # -- loading the existing component ---------------------------------------------------
    @staticmethod
    def _load_existing_detector():
        module = load_edge_agent_module("fight_detector")
        return module.FightDetector(model_version=settings.FIGHT_DETECTOR_VERSION, threshold=settings.FIGHT_CONFIDENCE_THRESHOLD)

    # -- proposed interface ---------------------------------------------------------------
    def initialize_anomaly_detector(self) -> bool:
        if not self.enabled:
            return False
        try:
            self._detector = self.detector_factory()
        except Exception as exc:  # model loading must never take the application down
            logger.exception("Anomaly detector failed to initialise")
            self._status, self._message = "error", f"Model initialisation failed: {type(exc).__name__}"
            return False
        if not any(getattr(self._detector, a, None) is not None for a in MODEL_ATTRIBUTES):
            self._status = "placeholder"
            self._message = (
                "Connected to edge-agent/fight_detector.py, but FightDetector holds no loaded model. "
                "Its predict_clip() is an inference placeholder, so no anomalies will be reported "
                "until the trained model is connected there."
            )
        else:
            self._status, self._message = "ready", "Connected to the existing fight classifier."
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="anomaly-worker", daemon=True)
        self._thread.start()
        return True

    def process_frame(self, camera_id: str, frame, timestamp: float) -> None:
        """Non-blocking: sample the frame into a clip buffer and queue full clips for inference."""
        if not self.enabled or self._detector is None:
            return
        with self._lock:
            n = self._frame_counters.get(camera_id, 0) + 1
            self._frame_counters[camera_id] = n
            if n % self.sample_every:
                return
            buf = self._buffers.setdefault(camera_id, [])
            buf.append(cv2.resize(frame, (self.clip_size, self.clip_size)))
            if len(buf) < self.clip_length:
                return
            clip, self._buffers[camera_id] = buf, []
        try:
            self._queue.put_nowait((camera_id, clip, timestamp))
        except queue.Full:
            self.dropped_clips += 1  # inference is behind; skip rather than block the camera

    def get_anomaly_events(self, since=None, limit: int = 50) -> List[dict]:
        from services.anomaly_store import list_anomaly_events

        return list_anomaly_events(since=since, limit=limit)

    def health_check(self) -> dict:
        return {
            "enabled": self.enabled,
            "status": self._status,
            "message": self._message,
            "model_name": settings.FIGHT_DETECTOR_MODEL,
            "model_version": settings.FIGHT_DETECTOR_VERSION,
            "threshold": self.threshold,
            "connection_point": "backend/edge-agent/fight_detector.py: FightDetector.predict_clip",
            "processed_clips": self.processed_clips,
            "dropped_clips": self.dropped_clips,
            "failed_inferences": self.failed_inferences,
            "last_inference_at": self.last_inference_at,
            "queue_depth": self._queue.qsize(),
        }

    def forget_camera(self, camera_id: str) -> None:
        with self._lock:
            self._buffers.pop(camera_id, None)
            self._frame_counters.pop(camera_id, None)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    # -- worker ---------------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                camera_id, clip, ts = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                output = self._detector.predict_clip(clip)
                self.processed_clips += 1
                self.last_inference_at = time.time()
            except Exception as exc:
                self.failed_inferences += 1
                self._status, self._message = "error", f"Inference failed: {type(exc).__name__}"
                logger.exception("Anomaly inference failed")
                continue
            result = self._interpret(camera_id, ts, output)
            if result is not None:
                try:
                    self.on_event(result)
                except Exception:
                    logger.exception("Failed to record anomaly event")

    def _interpret(self, camera_id: str, ts: float, output) -> Optional[AnomalyResult]:
        """Map the existing classifier's output format; anything malformed is ignored, not guessed."""
        if not isinstance(output, dict):
            return None
        try:
            is_fight = bool(output.get("is_fight"))
            confidence = float(output.get("confidence_score", 0.0))
        except (TypeError, ValueError):
            return None
        if not is_fight or confidence < self.threshold:
            return None
        return AnomalyResult(
            camera_id=camera_id,
            occurred_at=ts,
            label=str(output.get("label") or "Physical Altercation"),
            confidence=confidence,
            model_name=settings.FIGHT_DETECTOR_MODEL,
            model_version=str(getattr(self._detector, "model_version", settings.FIGHT_DETECTOR_VERSION)),
            raw_output={k: v for k, v in output.items() if isinstance(v, (str, int, float, bool, type(None)))},
        )
