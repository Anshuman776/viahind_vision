"""
Integration boundary for the video anomaly detector (VIAHIND-FightClassifier-MobileNetV3).

CONNECTION POINT: edge-agent/fight_detector.py -> FightDetector.predict_clip(frame_sequence, people)

Modes (VIDEO_ANOMALY_MODE):
- auto   (default): the trained classifier when FIGHT_MODEL_PATH is set, otherwise motion mode.
- model : the trained classifier only (startup reports an error without weights).
- motion: weight-free "vigorous movement between people" detector (vision/motion_anomaly.py).

Design rules:
- Disabled unless ANOMALY_DETECTION_ENABLED=True.
- Runs in its own thread with a bounded queue; clips are dropped (and counted) rather than
  ever blocking the camera or the person-tracking pipeline.
- Only outputs the detector actually produced are recorded. A failing model produces an error
  status, not alerts. Positives must repeat for ANOMALY_MIN_CONSECUTIVE_CLIPS clips in a row.
- Each recorded result carries a downscaled evidence frame for human review.
"""

import inspect
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2

from config import settings
from vision.edge_agent import load_edge_agent_module

logger = logging.getLogger("viahind.anomaly")

MODEL_ATTRIBUTES = ("model", "session", "net", "interpreter", "engine")
EVIDENCE_WIDTH = 640


@dataclass(frozen=True)
class AnomalyResult:
    camera_id: str
    occurred_at: float
    label: str
    confidence: float
    model_name: str
    model_version: str
    raw_output: dict
    snapshot_jpeg: Optional[bytes] = field(default=None, repr=False, compare=False)


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
        min_consecutive: Optional[int] = None,
    ):
        self.enabled = settings.ANOMALY_DETECTION_ENABLED if enabled is None else enabled
        self.on_event = on_event
        self.detector_factory = detector_factory or self._load_existing_detector
        self.sample_every = max(1, sample_every_n_frames or settings.ANOMALY_SAMPLE_EVERY_N_FRAMES)
        self.clip_length = max(2, clip_length or settings.ANOMALY_CLIP_LENGTH)
        self.threshold = settings.FIGHT_CONFIDENCE_THRESHOLD if threshold is None else threshold
        self.clip_size = clip_size
        self.min_consecutive = max(1, min_consecutive or settings.ANOMALY_MIN_CONSECUTIVE_CLIPS)

        self._detector = None
        self._accepts_people = False
        self.mode = "disabled"
        self._status = "disabled" if not self.enabled else "not_initialized"
        self._message = "Video anomaly detection is disabled (ANOMALY_DETECTION_ENABLED=False)." if not self.enabled else ""
        self._queue: "queue.Queue[tuple]" = queue.Queue(maxsize=2)
        self._buffers: Dict[str, List] = {}
        self._boxes: Dict[str, List] = {}
        self._latest: Dict[str, object] = {}
        self._frame_counters: Dict[str, int] = {}
        self._streak: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.processed_clips = 0
        self.dropped_clips = 0
        self.failed_inferences = 0
        self.positive_clips = 0
        self.last_inference_at: Optional[float] = None
        self.last_inference_ms: Optional[float] = None

    # -- loading the detector -----------------------------------------------------------------
    @staticmethod
    def _load_existing_detector():
        module = load_edge_agent_module("fight_detector")
        return module.FightDetector(
            model_version=settings.FIGHT_DETECTOR_VERSION,
            threshold=settings.FIGHT_CONFIDENCE_THRESHOLD if settings.FIGHT_CONFIDENCE_THRESHOLD_SET else None,
            model_path=settings.FIGHT_MODEL_PATH,
            mode=settings.VIDEO_ANOMALY_MODE,
            device=settings.DETECTION_DEVICE,
            expected_sha256=settings.FIGHT_MODEL_SHA256,
            motion_threshold=settings.MOTION_ANOMALY_THRESHOLD,
        )

    def initialize_anomaly_detector(self) -> bool:
        if not self.enabled:
            return False
        try:
            self._detector = self.detector_factory()
        except Exception as exc:  # model loading must never take the application down
            logger.exception("Video anomaly detector failed to initialise")
            self._status, self._message = "error", f"Model initialisation failed: {type(exc).__name__}: {str(exc)[:160]}"
            return False
        try:
            self._accepts_people = "people" in inspect.signature(self._detector.predict_clip).parameters
        except (TypeError, ValueError):
            self._accepts_people = False
        self.mode = getattr(self._detector, "mode", None) or ("model" if self._has_model() else "placeholder")
        if self.mode == "model":
            meta = getattr(self._detector, "meta", {}) or {}
            metrics = meta.get("holdout_metrics") or {}
            detail = f" Hold-out accuracy {metrics.get('accuracy')}, F1 {metrics.get('f1')}." if metrics else ""
            self._status, self._message = "ready", f"Trained classifier {getattr(self._detector, 'model_version', '')} loaded.{detail}"
            self.threshold = float(getattr(self._detector, "threshold", self.threshold))
        elif self.mode == "motion":
            self._status = "motion"
            self._message = ("No trained classifier is configured, so the weight-free motion detector is active: it reports "
                             "vigorous movement between people in close contact (not fights). Set FIGHT_MODEL_PATH to a "
                             "trained model to use the classifier.")
        else:
            self._status = "placeholder"
            self._message = "The detector holds no loaded model; no anomalies will be reported."
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="anomaly-worker", daemon=True)
        self._thread.start()
        return True

    def _has_model(self) -> bool:
        return any(getattr(self._detector, a, None) is not None for a in MODEL_ATTRIBUTES)

    # -- frames in ---------------------------------------------------------------------------
    def process_frame(self, camera_id: str, frame, timestamp: float, people: Optional[Sequence[Tuple[float, float, float, float]]] = None) -> None:
        """Non-blocking: sample the frame (and the people boxes, in pixels) into a clip buffer."""
        if not self.enabled or self._detector is None:
            return
        with self._lock:
            n = self._frame_counters.get(camera_id, 0) + 1
            self._frame_counters[camera_id] = n
            if n % self.sample_every:
                return
            h, w = frame.shape[:2]
            buf = self._buffers.setdefault(camera_id, [])
            boxes = self._boxes.setdefault(camera_id, [])
            buf.append(cv2.resize(frame, (self.clip_size, self.clip_size)))
            boxes.append([(b[0] / w, b[1] / h, b[2] / w, b[3] / h) for b in (people or [])])
            self._latest[camera_id] = frame
            if len(buf) < self.clip_length:
                return
            clip, clip_boxes, evidence = buf, boxes, self._latest[camera_id]
            self._buffers[camera_id], self._boxes[camera_id] = [], []
        try:
            self._queue.put_nowait((camera_id, clip, clip_boxes, evidence, timestamp))
        except queue.Full:
            self.dropped_clips += 1  # inference is behind; skip rather than block the camera

    def get_anomaly_events(self, organization_id: int, since=None, limit: int = 50) -> List[dict]:
        from services.anomaly_store import list_anomaly_events

        return list_anomaly_events(organization_id, since=since, limit=limit)

    def health_check(self) -> dict:
        meta = getattr(self._detector, "meta", {}) or {}
        return {
            "enabled": self.enabled,
            "status": self._status,
            "mode": self.mode,
            "message": self._message,
            "model_name": settings.FIGHT_DETECTOR_MODEL,
            "model_version": getattr(self._detector, "model_version", None),
            "threshold": self.threshold,
            "holdout_metrics": meta.get("holdout_metrics"),
            "trained_at": meta.get("trained_at"),
            "min_consecutive_clips": self.min_consecutive,
            "connection_point": "backend/edge-agent/fight_detector.py: FightDetector.predict_clip",
            "processed_clips": self.processed_clips,
            "positive_clips": self.positive_clips,
            "dropped_clips": self.dropped_clips,
            "failed_inferences": self.failed_inferences,
            "last_inference_at": self.last_inference_at,
            "last_inference_ms": self.last_inference_ms,
            "queue_depth": self._queue.qsize(),
        }

    def forget_camera(self, camera_id: str) -> None:
        with self._lock:
            for d in (self._buffers, self._boxes, self._latest, self._frame_counters, self._streak):
                d.pop(camera_id, None)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    # -- worker ---------------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                camera_id, clip, boxes, evidence, ts = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            started = time.perf_counter()
            try:
                if self._accepts_people:
                    output = self._detector.predict_clip(clip, people=boxes)
                else:
                    output = self._detector.predict_clip(clip)
                self.processed_clips += 1
                self.last_inference_at = time.time()
                self.last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
                if self._status == "error":
                    self._status = "ready" if self.mode == "model" else self.mode
            except Exception as exc:
                self.failed_inferences += 1
                self._status, self._message = "error", f"Inference failed: {type(exc).__name__}"
                logger.exception("Video anomaly inference failed")
                continue
            result = self._interpret(camera_id, ts, output, evidence)
            if result is not None:
                try:
                    self.on_event(result)
                except Exception:
                    logger.exception("Failed to record anomaly event")

    def _interpret(self, camera_id: str, ts: float, output, evidence=None) -> Optional[AnomalyResult]:
        """Map the detector output; anything malformed is ignored, not guessed."""
        if not isinstance(output, dict):
            return None
        try:
            hit = bool(output.get("is_anomaly", output.get("is_fight")))
            confidence = float(output.get("confidence_score", 0.0))
        except (TypeError, ValueError):
            return None
        if output.get("mode", "model") != "motion" and confidence < self.threshold:
            hit = False
        with self._lock:
            streak = self._streak.get(camera_id, 0) + 1 if hit else 0
            self._streak[camera_id] = streak
        if not hit:
            return None
        self.positive_clips += 1
        if streak < self.min_consecutive:
            return None
        with self._lock:
            self._streak[camera_id] = 0  # one alert per confirmed run; the alert engine deduplicates further
        jpeg = None
        if evidence is not None:
            img = evidence
            if img.shape[1] > EVIDENCE_WIDTH:
                img = cv2.resize(img, (EVIDENCE_WIDTH, int(img.shape[0] * EVIDENCE_WIDTH / img.shape[1])))
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            jpeg = buf.tobytes() if ok else None
        raw = {k: v for k, v in output.items() if isinstance(v, (str, int, float, bool, type(None)))}
        if isinstance(output.get("metrics"), dict):
            raw["metrics"] = {k: v for k, v in output["metrics"].items() if isinstance(v, (int, float, str, bool))}
        raw["consecutive_clips"] = streak
        return AnomalyResult(
            camera_id=camera_id,
            occurred_at=ts,
            label=str(output.get("label") or "Video anomaly"),
            confidence=confidence,
            model_name=settings.FIGHT_DETECTOR_MODEL if output.get("mode") != "motion" else "VIAHIND-MotionContact",
            model_version=str(getattr(self._detector, "model_version", settings.FIGHT_DETECTOR_VERSION)),
            raw_output=raw,
            snapshot_jpeg=jpeg,
        )
