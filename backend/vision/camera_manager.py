"""Owns the per-camera workers and connects them to persistence, live viewers and settings."""

import logging
import threading
from typing import Callable, Dict, Optional

from sqlalchemy import select

from config import settings
from db import session_scope
from models.entities import Camera
from services.incidents import close_incidents, open_incident
from services.site_settings import crossing_params, get_site_settings
from vision.camera_worker import CameraSpec, CameraWorker
from vision.detector import create_person_detector, detector_availability
from vision.edge_agent import load_edge_agent_module
from vision.line_crossing import CrossingParams, LineConfig
from vision.sources import SourceError, decrypt_source, resolve_source

logger = logging.getLogger("viahind.cameras")


def line_from_camera(cam: Camera) -> Optional[LineConfig]:
    if not cam.has_line:
        return None
    return LineConfig(cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2, 1 if cam.entry_side >= 0 else -1)


def default_reader_factory(camera_id, source):
    return load_edge_agent_module("rtsp_reader").RTSPReader(camera_id, source)


class CameraManager:
    def __init__(
        self,
        recorder,
        publisher=None,
        anomaly=None,
        detector_factory: Callable[[], object] = create_person_detector,
        reader_factory: Callable = default_reader_factory,
    ):
        self.recorder = recorder
        self.publisher = publisher
        self.anomaly = anomaly
        self.detector_factory = detector_factory
        self.reader_factory = reader_factory
        self._workers: Dict[str, CameraWorker] = {}
        self._lock = threading.RLock()
        self._params = CrossingParams()

    # -- settings -----------------------------------------------------------------------------
    def refresh_params(self) -> None:
        with session_scope() as db:
            self._params = crossing_params(get_site_settings(db))

    def params(self) -> CrossingParams:
        return self._params

    # -- lifecycle ----------------------------------------------------------------------------
    def start(self, camera_id: str, persist: bool = True, monitoring_established: bool = False) -> dict:
        """Start (or restart) a camera. Raises SourceError / LookupError with operator-safe messages."""
        with session_scope() as db:
            cam = db.get(Camera, camera_id)
            if cam is None:
                raise LookupError("Camera not found.")
            if not cam.enabled:
                raise SourceError("This camera is disabled in Settings.")
            source = None
            if cam.source_type != "browser":
                if not cam.source_secret:
                    raise SourceError("No source is configured for this camera. Add it in Settings.")
                source = resolve_source(cam.source_type, decrypt_source(cam.source_secret))
            spec = CameraSpec(
                id=cam.id,
                name=cam.name,
                source_type=cam.source_type,
                source=source,
                line=line_from_camera(cam),
                detection_enabled=cam.detection_enabled,
            )
            if persist:
                cam.desired_running = True

        with self._lock:
            existing = self._workers.pop(camera_id, None)
            was_monitoring = monitoring_established or (existing is not None and existing.monitoring_established)
            if existing is not None:
                existing.stop()
            worker = CameraWorker(
                spec,
                params_provider=self.params,
                detector_factory=self.detector_factory,
                recorder=self.recorder,
                publisher=self.publisher,
                anomaly=self.anomaly,
                reader_factory=self.reader_factory,
                on_interruption=lambda cid, kind, msg: open_incident(cid, kind, msg),
                on_recovery=close_incidents,
                detector_unavailable_reason=lambda: detector_availability()[1],
                stale_seconds=settings.CAMERA_STALE_SECONDS,
                detection_max_fps=settings.DETECTION_MAX_FPS,
                viewer_max_fps=settings.VIEWER_MAX_FPS,
                monitoring_established=was_monitoring,
            )
            self._workers[camera_id] = worker
            worker.start()
            return worker.snapshot()

    def stop(self, camera_id: str, persist: bool = True) -> dict:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is not None:
            worker.stop()
        if persist:
            with session_scope() as db:
                cam = db.get(Camera, camera_id)
                if cam is not None:
                    cam.desired_running = False
        # A deliberate stop is not an interruption; close any open incident for this camera.
        close_incidents(camera_id)
        return self.status(camera_id)

    def reconnect(self, camera_id: str) -> dict:
        """Tear the worker down and start a fresh one (also recovers crashed workers)."""
        return self.start(camera_id, persist=True)

    def resume_on_startup(self) -> None:
        """Restart cameras that were running before the service stopped and log the gap."""
        with session_scope() as db:
            ids = list(db.scalars(select(Camera.id).where(Camera.desired_running.is_(True), Camera.enabled.is_(True))))
        for camera_id in ids:
            open_incident(camera_id, "service_restart", "The service restarted; events during the downtime were not recorded.")
            try:
                # The camera was monitoring before the restart, so later failures are interruptions.
                self.start(camera_id, persist=False, monitoring_established=True)
            except (SourceError, LookupError) as exc:
                logger.error("Could not resume camera %s: %s", camera_id, exc)

    def shutdown(self) -> None:
        with self._lock:
            workers, self._workers = list(self._workers.values()), {}
        for worker in workers:
            worker.stop()

    # -- runtime ------------------------------------------------------------------------------
    def worker(self, camera_id: str) -> Optional[CameraWorker]:
        return self._workers.get(camera_id)

    def status(self, camera_id: str) -> dict:
        worker = self._workers.get(camera_id)
        if worker is None:
            return {
                "camera_id": camera_id,
                "status": "stopped",
                "message": "",
                "last_frame_at": None,
                "fps": 0.0,
                "detection_status": "off",
                "detection_message": "",
                "tracked_people": 0,
                "events_recorded": 0,
                "started_at": None,
                "frame_size": None,
            }
        return worker.snapshot()

    def push_frame(self, camera_id: str, frame: bytes) -> bool:
        worker = self._workers.get(camera_id)
        if worker is None or worker.spec.source_type != "browser":
            return False
        worker.push_frame(frame)
        return True

    def update_line(self, camera_id: str, line: Optional[LineConfig]) -> None:
        worker = self._workers.get(camera_id)
        if worker is not None:
            worker.update_line(line)

    def running_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == "live")
