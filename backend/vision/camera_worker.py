"""
Per-camera worker: capture -> person tracking -> line crossing / zones -> events, plus live view frames.

Threads per camera:
- capture  (server-side sources only): reads frames from USB / RTSP / HTTP / test clips with
           reconnect and back-off. Browser cameras push frames through push_frame() instead.
- process: runs the person detector on the most recent frame (older frames are dropped, so a
           slow model never builds a backlog), feeds LineCrossingCounter, saves event snapshots
           and hands events to the recorder. Also feeds the anomaly adapter (non-blocking).
- viewer:  publishes the latest frame with overlay data to live viewers at a capped rate.

A camera is reported "live" only while frames are actually arriving.
"""

import base64
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol, Tuple, Union

import cv2
import numpy as np

from vision.line_crossing import CrossingEvent, CrossingParams, Detection, LineConfig, LineCrossingCounter
from vision.quality import measure_quality
from vision.zones import ZoneConfig, ZoneEvent, ZoneMonitor

logger = logging.getLogger("viahind.camera")

SNAPSHOT_MAX_AGE = 2.0  # seconds a buffered best crop stays relevant for an event
QUALITY_INTERVAL = 5.0  # seconds between image-quality measurements


@dataclass
class CameraSpec:
    id: str
    name: str
    source_type: str  # browser | device | network | file
    source: Union[int, str, None]
    line: Optional[LineConfig]
    detection_enabled: bool = True
    organization_id: Optional[int] = None
    location_id: Optional[int] = None
    zones: Tuple[ZoneConfig, ...] = ()


class Publisher(Protocol):
    def has_viewers(self, camera_id: str) -> bool: ...
    def publish_frame(self, camera_id: str, payload: dict) -> None: ...
    def publish_status(self, camera_id: str, status: dict) -> None: ...


class Recorder(Protocol):
    def record(self, camera_id: str, session_id: str, crossing: CrossingEvent, snapshot_jpeg: Optional[bytes], **kwargs) -> Optional[dict]: ...


# zone_sink(spec, session_id, zone_event, snapshot_jpeg)
ZoneSink = Callable[["CameraSpec", str, ZoneEvent, Optional[bytes]], None]


class NullPublisher:
    def has_viewers(self, camera_id: str) -> bool:
        return False

    def publish_frame(self, camera_id: str, payload: dict) -> None:
        pass

    def publish_status(self, camera_id: str, status: dict) -> None:
        pass


def crop_snapshot(frame: np.ndarray, box) -> Optional[np.ndarray]:
    """Crop a person with some context around the box."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    if bw <= 2 or bh <= 2:
        return None
    x1, x2 = int(max(0, x1 - 0.2 * bw)), int(min(w, x2 + 0.2 * bw))
    y1, y2 = int(max(0, y1 - 0.1 * bh)), int(min(h, y2 + 0.1 * bh))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return frame[y1:y2, x1:x2].copy()


def encode_jpeg(image: np.ndarray, quality: int = 90, max_width: Optional[int] = None) -> Optional[bytes]:
    if max_width and image.shape[1] > max_width:
        scale = max_width / image.shape[1]
        image = cv2.resize(image, (max_width, int(image.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else None


class CameraWorker:
    def __init__(
        self,
        spec: CameraSpec,
        params_provider: Callable[[], CrossingParams],
        detector_factory: Callable[[], object],
        recorder: Recorder,
        publisher: Optional[Publisher] = None,
        anomaly=None,
        reader_factory: Optional[Callable] = None,
        on_interruption: Optional[Callable[[str, str, str], None]] = None,
        on_recovery: Optional[Callable[[str], None]] = None,
        detector_unavailable_reason: Callable[[], str] = lambda: "Person detection is not configured.",
        monitoring_established: bool = False,
        stale_seconds: float = 5.0,
        detection_max_fps: float = 8.0,
        viewer_max_fps: float = 8.0,
        clock: Callable[[], float] = time.time,
        zone_sink: Optional[ZoneSink] = None,
        evidence_policy: Optional[Callable[[], object]] = None,
    ):
        self.spec = spec
        self.params_provider = params_provider
        self.detector_factory = detector_factory
        self.recorder = recorder
        self.publisher = publisher or NullPublisher()
        self.anomaly = anomaly
        self.reader_factory = reader_factory
        self.on_interruption = on_interruption
        self.on_recovery = on_recovery
        self.detector_unavailable_reason = detector_unavailable_reason
        # True once this camera has delivered frames (in this worker or the one it replaced).
        # Before that the camera was never monitoring, so a failure is a setup error shown in the
        # camera status, not an interruption that could have caused missed entries/exits.
        self.monitoring_established = monitoring_established
        self.stale_seconds = stale_seconds
        self.detection_interval = 1.0 / max(0.1, detection_max_fps)
        self.viewer_interval = 1.0 / max(0.1, viewer_max_fps)
        self.clock = clock
        self.zone_sink = zone_sink
        self.evidence_policy = evidence_policy

        self.session_id = str(uuid.uuid4())
        params = params_provider()
        self.counter = LineCrossingCounter(spec.line, params)
        self.zones = ZoneMonitor(spec.zones, min_confidence=params.min_confidence, anchor=params.anchor)
        self._pending_line: Optional[Tuple[Optional[LineConfig]]] = None
        self._pending_zones: Optional[Tuple[ZoneConfig, ...]] = None
        self.quality: Optional[dict] = None
        self._last_quality = 0.0
        self._zone_counts: Dict[int, int] = {}
        self._lock = threading.Lock()
        self._frame_cond = threading.Condition()
        self._frame: Union[np.ndarray, bytes, None] = None
        self._frame_seq = 0
        self._frame_ts = 0.0
        self._stop = threading.Event()
        self._crashed = False
        self._detector_ready = threading.Event()
        self._reconnect = threading.Event()
        self._threads: List[threading.Thread] = []
        self._candidates: Dict[int, Tuple[float, float, np.ndarray]] = {}
        self._labels: Dict[int, str] = {}
        self._overlay: List[dict] = []
        self._visible_people = 0
        self._frame_size: Optional[Tuple[int, int]] = None
        self._fps_count = 0
        self._fps_started = time.monotonic()

        self.status = "stopped"
        self.message = ""
        self.last_frame_at: Optional[float] = None
        self.fps = 0.0
        self.detection_status = "off"
        self.detection_message = ""
        self.events_recorded = 0
        self.started_at: Optional[float] = None

    # -- lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self.started_at = self.clock()
        if self.spec.source_type == "browser":
            self._set_status("connecting", "Waiting for frames from the operator's browser.")
        else:
            self._set_status("connecting", "Opening camera stream...")
            self._spawn(self._capture_loop, "capture")
        self._spawn(self._process_loop, "process")
        self._spawn(self._viewer_loop, "viewer")

    def stop(self, join: bool = True) -> None:
        self._stop.set()
        self._detector_ready.set()
        with self._frame_cond:
            self._frame_cond.notify_all()
        if join:
            for t in self._threads:
                if t is not threading.current_thread():
                    t.join(timeout=5)
        self._threads.clear()
        if self.anomaly is not None:
            self.anomaly.forget_camera(self.spec.id)
        self._set_status("stopped", "")

    def reconnect(self) -> None:
        """Force the capture side to reopen the stream (server-side sources)."""
        self._reconnect.set()

    def update_line(self, line: Optional[LineConfig]) -> None:
        with self._lock:
            self._pending_line = (line,)

    def update_zones(self, zones: Tuple[ZoneConfig, ...]) -> None:
        with self._lock:
            self._pending_zones = tuple(zones)

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=self._guard(target), name=f"cam-{self.spec.id}-{name}", daemon=True)
        self._threads.append(t)
        t.start()

    def _guard(self, target):
        def run():
            try:
                target()
            except Exception as exc:  # a worker crash must surface as an error state, not vanish
                logger.exception("Camera %s worker thread crashed", self.spec.id)
                self._crashed = True  # sticky: arriving frames must not flip a dead pipeline back to "live"
                self._set_status("error", f"Camera worker failed: {type(exc).__name__}. Use Reconnect or restart the camera.")
                self._interrupted("error", f"Worker crashed: {type(exc).__name__}")

        return run

    # -- frames in ---------------------------------------------------------------------------
    def push_frame(self, frame: Union[np.ndarray, bytes]) -> None:
        """Accept a frame (BGR array or encoded JPEG bytes) from a browser stream or the capture thread."""
        if self._stop.is_set() or self._crashed:
            return
        now = self.clock()
        with self._frame_cond:
            self._frame = frame
            self._frame_seq += 1
            self._frame_ts = now
            self._frame_cond.notify_all()
        self.last_frame_at = now
        self._fps_count += 1
        elapsed = time.monotonic() - self._fps_started
        if elapsed >= 2.0:
            self.fps = round(self._fps_count / elapsed, 1)
            self._fps_count, self._fps_started = 0, time.monotonic()
        if self.status != "live":
            self._set_status("live", "")
            self.monitoring_established = True
            # Incidents are persisted per camera, not per worker: a worker created by Reconnect or a
            # source change must also close interruptions recorded by the worker it replaced.
            if self.on_recovery:
                self.on_recovery(self.spec.id)

    def _capture_loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            reader = self.reader_factory(self.spec.id, self.spec.source)
            if not reader.connect():
                attempt += 1
                delay = min(30.0, 2.0 ** min(attempt, 5))
                self._set_status(
                    "disconnected" if self.monitoring_established else "error",
                    f"Could not open the camera stream (attempt {attempt}). Retrying in {int(delay)}s. "
                    "Check the address, credentials and that the camera is reachable from the server.",
                )
                if attempt == 1 and self.monitoring_established:
                    self._interrupted("error", "Camera stream could not be reopened.")
                self._wait_or_reconnect(delay)
                continue
            attempt = 0
            if getattr(reader, "is_file", False):
                # A test clip must not play past people while the model is still loading.
                self._detector_ready.wait(timeout=120)
            failures, index, started = 0, 0, time.monotonic()
            fps = getattr(reader, "file_fps", 0.0) if getattr(reader, "is_file", False) else 0.0
            try:
                while not self._stop.is_set() and not self._reconnect.is_set():
                    frame = reader.read_frame()
                    if frame is None:
                        if getattr(reader, "is_file", False):
                            self._set_status("ended", "The test clip has finished. Start the camera again to replay it.")
                            return
                        failures += 1
                        if failures >= 30:
                            break  # stream stalled: reopen it
                        time.sleep(0.05)
                        continue
                    failures = 0
                    self.push_frame(frame)
                    if fps > 0:
                        index += 1
                        delay = started + index / fps - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
            finally:
                reader.release()
            self._reconnect.clear()

    def _wait_or_reconnect(self, delay: float) -> None:
        if self._reconnect.wait(delay):
            self._reconnect.clear()

    # -- processing ----------------------------------------------------------------------------
    def _process_loop(self) -> None:
        try:
            detector = self._init_detector()
        finally:
            self._detector_ready.set()
        last_seq, last_run = 0, 0.0
        while not self._stop.is_set():
            with self._frame_cond:
                if self._frame_seq == last_seq:
                    self._frame_cond.wait(timeout=0.5)
                frame, seq, ts = self._frame, self._frame_seq, self._frame_ts
            if self._stop.is_set():
                break
            self._check_stale(detector)
            self._apply_pending_config()
            if frame is None or seq == last_seq:
                continue
            wait = self.detection_interval - (time.monotonic() - last_run)
            if wait > 0:
                time.sleep(wait)
                continue
            last_seq, last_run = seq, time.monotonic()

            image = self._decode(frame)
            if image is None:
                continue
            h, w = image.shape[:2]
            self._frame_size = (w, h)

            if ts - self._last_quality >= QUALITY_INTERVAL:
                self._last_quality = ts
                sample = measure_quality(image, ts)
                self.quality = sample.as_dict() if sample else None

            detections: List[Detection] = []
            if detector is not None:
                try:
                    detections = detector.track(image)
                    if self.detection_status == "error":
                        self._refresh_detection_status()
                except Exception as exc:
                    self._set_detection("error", f"Detection failed on a frame: {type(exc).__name__}")
                    logger.exception("Detection failed on camera %s", self.spec.id)
                    continue
            if self.anomaly is not None:
                # People boxes let the motion detector look only at people in close contact.
                min_conf = self.counter.params.min_confidence
                people = [d.box for d in detections if d.track_id is not None and d.confidence >= min_conf] if detector is not None else None
                self.anomaly.process_frame(self.spec.id, image, ts, people)
            self._process_detections(image, ts, detections)

    def _init_detector(self):
        if not self.spec.detection_enabled:
            self._set_detection("off", "Person detection is turned off for this camera.")
            return None
        self._set_detection("loading", "Loading person detector...")
        try:
            detector = self.detector_factory()
        except Exception as exc:
            logger.exception("Person detector failed to initialise for camera %s", self.spec.id)
            self._set_detection("error", f"Person detector failed to load: {type(exc).__name__}. The live view still works.")
            return None
        if detector is None:
            self._set_detection("unavailable", self.detector_unavailable_reason())
            return None
        self._refresh_detection_status()
        return detector

    def _refresh_detection_status(self) -> None:
        """Called only while a detector is loaded and working."""
        if self.counter.line is None:
            self._set_detection("no_line", "Detecting people. Draw the entrance line to start recording entries and exits.")
        else:
            self._set_detection("active", "")

    def _apply_pending_config(self) -> None:
        with self._lock:
            pending, self._pending_line = self._pending_line, None
            pending_zones, self._pending_zones = self._pending_zones, None
        if pending_zones is not None:
            self.zones.set_zones(pending_zones)
        if pending is not None:
            self.counter.set_line(pending[0])
            self._candidates.clear()
            if self.detection_status in ("active", "no_line"):
                self._refresh_detection_status()
        params = self.params_provider()
        if params != self.counter.params:
            self.counter.set_params(params)
            self.zones.min_confidence, self.zones.anchor = params.min_confidence, params.anchor

    def _decode(self, frame) -> Optional[np.ndarray]:
        if isinstance(frame, np.ndarray):
            return frame
        image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            logger.warning("Camera %s: discarded a frame that could not be decoded", self.spec.id)
        return image

    def _process_detections(self, image: np.ndarray, ts: float, detections: List[Detection]) -> None:
        params = self.counter.params
        for det in detections:
            if det.track_id is None or det.confidence < params.min_confidence:
                continue
            area = max(1.0, (det.box[2] - det.box[0]) * (det.box[3] - det.box[1]))
            score = det.confidence * float(np.sqrt(area))
            current = self._candidates.get(det.track_id)
            if current is None or ts - current[1] > SNAPSHOT_MAX_AGE or score >= current[0]:
                crop = crop_snapshot(image, det.box)
                if crop is not None:
                    self._candidates[det.track_id] = (score, ts, crop)

        events = self.counter.update(detections, ts, (image.shape[1], image.shape[0]))
        for event in events:
            self._record(event, image, ts)
        for zone_event in self.zones.update(detections, ts, (image.shape[1], image.shape[0])):
            self._zone_event(zone_event, image)
        self._zone_counts = self.zones.occupancy()

        live_ids = set(self.counter.tracks)
        for tid in [t for t in self._candidates if t not in live_ids]:
            del self._candidates[tid]
        for tid in [t for t in self._labels if t not in live_ids]:
            del self._labels[tid]

        # Draw only people detected in this frame; remembered-but-unseen tracks would be ghosts.
        visible_ids = {d.track_id for d in detections if d.track_id is not None}
        overlay = []
        for item in self.counter.overlay_tracks():
            if item["track_id"] in visible_ids:
                item["label"] = self._labels.get(item["track_id"])
                overlay.append(item)
        for det in detections:
            if det.track_id is None or det.track_id not in live_ids:
                overlay.append({"track_id": det.track_id, "box": [round(v, 1) for v in det.box], "side": "unknown", "last_event": None, "label": None})
        self._overlay = overlay
        self._visible_people = sum(1 for d in detections if d.confidence >= params.min_confidence)

    def _record(self, event: CrossingEvent, image: np.ndarray, ts: float) -> None:
        crop = None
        candidate = self._candidates.get(event.track_id)
        if candidate is not None and ts - candidate[1] <= SNAPSHOT_MAX_AGE:
            crop = candidate[2]
        elif event.reason != "lost_while_crossing":
            crop = crop_snapshot(image, event.box)
        jpeg = self._encode_evidence(crop) if crop is not None else None
        if self.spec.organization_id is not None:
            result = self.recorder.record(self.spec.id, self.session_id, event, jpeg, organization_id=self.spec.organization_id)
        else:
            result = self.recorder.record(self.spec.id, self.session_id, event, jpeg)
        if result is not None:
            self.events_recorded += 1
            self._labels[event.track_id] = result.get("person_label")

    def _encode_evidence(self, image: np.ndarray) -> Optional[bytes]:
        policy = self.evidence_policy() if self.evidence_policy else None
        if policy is None:
            return encode_jpeg(image, quality=90)
        return encode_jpeg(image, quality=int(policy.jpeg_quality), max_width=int(policy.max_width) or None)

    def _zone_event(self, event: ZoneEvent, image: np.ndarray) -> None:
        if self.zone_sink is None:
            return
        # Evidence for a zone alert: the person with some context, never the full stream.
        crop = crop_snapshot(image, event.box)
        jpeg = self._encode_evidence(crop) if crop is not None else None
        try:
            self.zone_sink(self.spec, self.session_id, event, jpeg)
        except Exception:
            logger.exception("Zone event handling failed on camera %s", self.spec.id)

    def _check_stale(self, detector) -> None:
        if self.status != "live" or self.last_frame_at is None:
            return
        if self.clock() - self.last_frame_at <= self.stale_seconds:
            return
        dropped = self.counter.reset()
        self.zones.reset()
        self._zone_counts = {}
        self._candidates.clear()
        self._labels.clear()
        self._overlay = []
        self._visible_people = 0
        if detector is not None:
            try:
                detector.reset()
            except Exception:
                logger.exception("Tracker reset failed on camera %s", self.spec.id)
        # Tracker IDs restart after a reset, so a new session keeps track records distinct.
        self.session_id = str(uuid.uuid4())
        message = "No frames received. Reconnecting..." if self.spec.source_type != "browser" else "The browser stopped sending frames."
        self._set_status("disconnected", message)
        detail = f"No frames for {self.stale_seconds:.0f}s"
        if dropped:
            detail += f"; {dropped} person(s) were mid-crossing"
        self._interrupted("disconnected", detail)

    def _interrupted(self, kind: str, message: str) -> None:
        if self.on_interruption:
            try:
                self.on_interruption(self.spec.id, kind, message)
            except Exception:
                logger.exception("Could not record interruption for camera %s", self.spec.id)

    # -- live view -----------------------------------------------------------------------------
    def _viewer_loop(self) -> None:
        last_seq = 0
        while not self._stop.wait(self.viewer_interval):
            if not self.publisher.has_viewers(self.spec.id):
                continue
            with self._frame_cond:
                frame, seq, ts = self._frame, self._frame_seq, self._frame_ts
            if frame is None or seq == last_seq or self.status != "live":
                continue
            last_seq = seq
            image = self._decode(frame)
            if image is None:
                continue
            jpeg = encode_jpeg(image, quality=70, max_width=960)
            if jpeg is None:
                continue
            line = self.counter.line
            self.publisher.publish_frame(
                self.spec.id,
                {
                    "type": "frame",
                    "camera_id": self.spec.id,
                    "ts": ts,
                    "width": image.shape[1],
                    "height": image.shape[0],
                    "image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
                    "tracks": self._overlay,
                    "line": None if line is None else {"x1": line.x1, "y1": line.y1, "x2": line.x2, "y2": line.y2, "entry_side": line.entry_side},
                    "zones": [{"id": z.id, "name": z.name, "kind": z.kind, "polygon": [list(p) for p in z.polygon], "count": self._zone_counts.get(z.id, 0)} for z in self.zones.zones],
                },
            )

    # -- status --------------------------------------------------------------------------------
    def _set_status(self, status: str, message: str) -> None:
        changed = status != self.status or message != self.message
        self.status, self.message = status, message
        if changed:
            self.publisher.publish_status(self.spec.id, self.snapshot())

    def _set_detection(self, status: str, message: str) -> None:
        changed = status != self.detection_status or message != self.detection_message
        self.detection_status, self.detection_message = status, message
        if changed:
            self.publisher.publish_status(self.spec.id, self.snapshot())

    def snapshot(self) -> dict:
        return {
            "camera_id": self.spec.id,
            "status": self.status,
            "message": self.message,
            "last_frame_at": self.last_frame_at,
            "fps": self.fps,
            "detection_status": self.detection_status,
            "detection_message": self.detection_message,
            "tracked_people": self._visible_people,
            "events_recorded": self.events_recorded,
            "started_at": self.started_at,
            "frame_size": self._frame_size,
            "quality": self.quality,
            "session_id": self.session_id,
            "organization_id": self.spec.organization_id,
        }

    def latest_jpeg(self) -> Optional[bytes]:
        with self._frame_cond:
            frame = self._frame
        if frame is None:
            return None
        if isinstance(frame, bytes):
            return frame
        return encode_jpeg(frame, quality=85)
