"""Owns the per-camera workers and connects them to persistence, live viewers and settings."""

import json
import logging
import threading
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import select

from config import settings
from db import session_scope
from models.entities import Camera, CameraZone
from services.guards import watches_fights
from services.incidents import close_incidents, open_incident, record_camera_error
from services.site_settings import crossing_params, get_site_settings
from vision.camera_worker import CameraSpec, CameraWorker
from vision.detector import create_person_detector, detector_availability
from vision.edge_agent import load_edge_agent_module
from vision.line_crossing import CrossingParams, LineConfig
from vision.sources import SourceError, decrypt_source, resolve_source
from vision.zones import ZoneConfig

logger = logging.getLogger("viahind.cameras")


def line_from_camera(cam: Camera) -> Optional[LineConfig]:
    if not cam.has_line or not cam.counting_enabled:
        return None
    return LineConfig(cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2, 1 if cam.entry_side >= 0 else -1)


def zones_for_camera(db, camera_id: str) -> Tuple[ZoneConfig, ...]:
    zones: List[ZoneConfig] = []
    for z in db.scalars(select(CameraZone).where(CameraZone.camera_id == camera_id, CameraZone.enabled.is_(True))):
        try:
            polygon = tuple((float(x), float(y)) for x, y in json.loads(z.polygon))
        except (ValueError, TypeError):
            logger.warning("Zone %s has an invalid polygon; ignored", z.id)
            continue
        zones.append(ZoneConfig(z.id, z.name, z.kind, polygon, z.dwell_seconds))
    return tuple(zones)


class _StatusRecorder:
    """Publisher proxy that also persists the camera's last error for diagnostics."""

    def __init__(self, inner):
        self.inner = inner
        self._last: Dict[str, Optional[str]] = {}

    def has_viewers(self, camera_id: str) -> bool:
        return self.inner.has_viewers(camera_id) if self.inner else False

    def publish_frame(self, camera_id: str, payload: dict) -> None:
        if self.inner:
            self.inner.publish_frame(camera_id, payload)

    def publish_status(self, camera_id: str, status: dict) -> None:
        if self.inner:
            self.inner.publish_status(camera_id, status)
        error = status.get("message") if status.get("status") in ("error", "disconnected") else None
        if status.get("status") == "live":
            error = None
        elif error is None:
            return
        if self._last.get(camera_id, "unset") != error:
            self._last[camera_id] = error
            record_camera_error(camera_id, error)


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
        zone_sink: Optional[Callable] = None,
        evidence_policy: Optional[Callable[[int], object]] = None,
    ):
        self.recorder = recorder
        self.publisher = _StatusRecorder(publisher)
        self.zone_sink = zone_sink
        self.evidence_policy = evidence_policy
        self.anomaly = anomaly
        self.detector_factory = detector_factory
        self.reader_factory = reader_factory
        self._workers: Dict[str, CameraWorker] = {}
        self._lock = threading.RLock()
        self._params: Dict[int, CrossingParams] = {}

    # -- settings -----------------------------------------------------------------------------
    def refresh_params(self, organization_id: Optional[int] = None) -> None:
        """Reload detection parameters (one set per organization)."""
        with session_scope() as db:
            if organization_id is not None:
                org_ids = [organization_id]
            else:
                org_ids = list(db.scalars(select(Camera.organization_id).distinct()))
            for org_id in org_ids:
                self._params[org_id] = crossing_params(get_site_settings(db, org_id))

    def params_for(self, organization_id: Optional[int]) -> Callable[[], CrossingParams]:
        return lambda: self._params.get(organization_id, CrossingParams())

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
                organization_id=cam.organization_id,
                location_id=cam.location_id,
                zones=zones_for_camera(db, cam.id),
                fight_watch=watches_fights(cam),
            )
            if persist:
                cam.desired_running = True
            if cam.organization_id not in self._params:
                self._params[cam.organization_id] = crossing_params(get_site_settings(db, cam.organization_id))
        org_id = spec.organization_id
        policy = (lambda: self.evidence_policy(org_id)) if self.evidence_policy else None

        with self._lock:
            if camera_id not in self._workers and len(self._workers) >= settings.MAX_SIMULTANEOUS_STREAMS:
                raise SourceError(f"This server already processes {settings.MAX_SIMULTANEOUS_STREAMS} cameras (MAX_SIMULTANEOUS_STREAMS). Stop another camera first.")
            existing = self._workers.pop(camera_id, None)
            was_monitoring = monitoring_established or (existing is not None and existing.monitoring_established)
            if existing is not None:
                existing.stop()
            worker = CameraWorker(
                spec,
                params_provider=self.params_for(org_id),
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
                zone_sink=self.zone_sink,
                evidence_policy=policy,
                static_object_seconds=settings.STATIC_OBJECT_SECONDS,
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
                "quality": None,
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

    def reload_zones(self, camera_id: str) -> None:
        worker = self._workers.get(camera_id)
        if worker is None:
            return
        with session_scope() as db:
            zones = zones_for_camera(db, camera_id)
        worker.update_zones(zones)

    def set_fight_watch(self, camera_id: str, enabled: bool) -> None:
        """Apply a guard duty change without restarting the camera (no counting gap)."""
        worker = self._workers.get(camera_id)
        if worker is None or worker.spec.fight_watch == enabled:
            return
        worker.spec.fight_watch = enabled
        if not enabled and self.anomaly is not None:
            self.anomaly.forget_camera(camera_id)

    def workers(self) -> List[CameraWorker]:
        return list(self._workers.values())

    def running_count(self, organization_id: Optional[int] = None) -> int:
        return sum(
            1 for w in self._workers.values()
            if w.status == "live" and (organization_id is None or w.spec.organization_id == organization_id)
        )
