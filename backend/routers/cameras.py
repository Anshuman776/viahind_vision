"""
Camera inventory, lifecycle, counting line, zones and connection diagnostics.

Cameras belong to an organization and a location; every handler is tenant-scoped. Camera
sources are write-only; responses only include a masked description.
"""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_admin, require_operator, require_viewer
from config import settings
from db import get_db, utcnow
from models.entities import Camera, CameraZone, DetectionEvent, Organization, User
from models.schemas import CameraCreate, CameraUpdate, LineUpdate, SourceTest, ZoneBody
from runtime import runtime
from services.audit import record_audit
from services.tenancy import default_location, get_owned, owned_location
from vision.camera_manager import line_from_camera
from vision.sources import SourceError, decrypt_source, encrypt_source, mask_source, probe_tcp, resolve_source, validate_source

router = APIRouter(prefix="/cameras", tags=["cameras"])


def serialize_zone(z: CameraZone) -> dict:
    return {
        "id": z.id, "camera_id": z.camera_id, "name": z.name, "kind": z.kind, "polygon": json.loads(z.polygon),
        "dwell_seconds": z.dwell_seconds, "enabled": z.enabled,
    }


def serialize_camera(cam: Camera, db: Session = None, include_source: bool = True) -> dict:
    try:
        source = decrypt_source(cam.source_secret) if cam.source_secret else None
        source_description = mask_source(cam.source_type, source)
    except SourceError as exc:
        source_description = str(exc)
    status = runtime.cameras.status(cam.id) if runtime.cameras else {"status": "stopped"}
    zones = [serialize_zone(z) for z in db.scalars(select(CameraZone).where(CameraZone.camera_id == cam.id).order_by(CameraZone.id))] if db else []
    return {
        "id": cam.id,
        "name": cam.name,
        "location": cam.location,
        "location_id": cam.location_id,
        "source_type": cam.source_type,
        "source_description": source_description if include_source else None,
        "source_configured": cam.source_type == "browser" or bool(cam.source_secret),
        "enabled": cam.enabled,
        "detection_enabled": cam.detection_enabled,
        "counting_enabled": cam.counting_enabled,
        "desired_running": cam.desired_running,
        "line": None
        if not cam.has_line
        else {"x1": cam.line_x1, "y1": cam.line_y1, "x2": cam.line_x2, "y2": cam.line_y2, "entry_side": cam.entry_side},
        "zones": zones,
        "last_error": cam.last_error,
        "last_error_at": cam.last_error_at.isoformat() if cam.last_error_at else None,
        "runtime": status,
    }


def _get_camera(db: Session, camera_id: str, user: User) -> Camera:
    return get_owned(db, Camera, camera_id, user, "Camera not found.")


@router.get("")
def list_cameras(location_id: int = None, db: Session = Depends(get_db), user: User = Depends(require_viewer)):
    q = select(Camera).where(Camera.organization_id == user.organization_id)
    if location_id is not None:
        q = q.where(Camera.location_id == location_id)
    # Viewers see status for dashboards, but not source descriptions.
    return [serialize_camera(c, db, include_source=user.role != "viewer") for c in db.scalars(q.order_by(Camera.name))]


@router.get("/{camera_id}")
def get_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return serialize_camera(_get_camera(db, camera_id, user), db)


@router.post("", status_code=201)
def create_camera(body: CameraCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    org = db.get(Organization, admin.organization_id)
    if org.max_cameras is not None:
        count = db.scalar(select(func.count()).select_from(Camera).where(Camera.organization_id == org.id)) or 0
        if count >= org.max_cameras:
            raise HTTPException(status_code=402, detail=f"Your plan allows {org.max_cameras} camera(s). Upgrade the plan to add more.")
    if db.get(Camera, body.id) is not None:
        raise HTTPException(status_code=409, detail="This camera ID is not available. Choose another ID.")
    location = owned_location(db, admin, body.location_id) if body.location_id is not None else default_location(db, admin.organization_id)
    try:
        source = validate_source(body.source_type, body.source)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    cam = Camera(
        id=body.id,
        organization_id=admin.organization_id,
        location_id=location.id,
        name=body.name,
        location=body.location,
        source_type=body.source_type,
        source_secret=encrypt_source(source) if source else None,
        detection_enabled=body.detection_enabled,
        counting_enabled=body.counting_enabled,
    )
    db.add(cam)
    record_audit(db, admin, "camera.create", "camera", cam.id, {"name": cam.name, "source_type": cam.source_type, "location_id": location.id})
    db.commit()
    return serialize_camera(cam, db)


@router.patch("/{camera_id}")
def update_camera(camera_id: str, body: CameraUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id, admin)
    changes = {}
    for field in ("name", "location", "enabled", "detection_enabled", "counting_enabled"):
        value = getattr(body, field)
        if value is not None and value != getattr(cam, field):
            changes[field] = [getattr(cam, field), value]
            setattr(cam, field, value.strip() if isinstance(value, str) else value)
    if body.location_id is not None and body.location_id != cam.location_id:
        owned_location(db, admin, body.location_id)
        changes["location_id"] = [cam.location_id, body.location_id]
        cam.location_id = body.location_id
    new_type = body.source_type or cam.source_type
    if body.source is not None or new_type != cam.source_type:
        if body.source is None and new_type != "browser":
            raise HTTPException(status_code=422, detail="Enter the camera source for the new camera type.")
        try:
            source = validate_source(new_type, body.source)
        except SourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        cam.source_type = new_type
        cam.source_secret = encrypt_source(source) if source else None
        changes["source"] = "replaced"  # never log the source itself
    cam.updated_at = utcnow()
    if changes:
        record_audit(db, admin, "camera.update", "camera", cam.id, changes)
    db.commit()
    running = runtime.cameras and runtime.cameras.worker(cam.id) is not None
    restart_fields = {"source", "detection_enabled", "location_id", "counting_enabled"}
    if running and (restart_fields & set(changes) or changes.get("enabled") == [True, False]):
        if cam.enabled:
            try:
                runtime.cameras.start(cam.id)
            except SourceError:
                runtime.cameras.stop(cam.id)
        else:
            runtime.cameras.stop(cam.id)
    return serialize_camera(cam, db)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id, admin)
    events = db.scalar(select(func.count()).select_from(DetectionEvent).where(DetectionEvent.camera_id == camera_id))
    if events:
        raise HTTPException(status_code=409, detail="This camera has recorded events. Disable it instead of deleting it.")
    if runtime.cameras:
        runtime.cameras.stop(camera_id, persist=False)
    record_audit(db, admin, "camera.delete", "camera", camera_id, {"name": cam.name})
    db.delete(cam)
    db.commit()
    return Response(status_code=204)


def _lifecycle(camera_id: str, db: Session, user: User, action: str) -> dict:
    cam = _get_camera(db, camera_id, user)
    try:
        if action == "start":
            runtime.cameras.start(camera_id)
        elif action == "reconnect":
            runtime.cameras.reconnect(camera_id)
        else:
            runtime.cameras.stop(camera_id)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    record_audit(db, user, f"camera.{action}", "camera", camera_id, {})
    db.commit()
    db.refresh(cam)
    return serialize_camera(cam, db)


@router.post("/{camera_id}/start")
def start_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _lifecycle(camera_id, db, user, "start")


@router.post("/{camera_id}/stop")
def stop_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _lifecycle(camera_id, db, user, "stop")


@router.post("/{camera_id}/reconnect")
def reconnect_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _lifecycle(camera_id, db, user, "reconnect")


# -- connection testing -----------------------------------------------------------------------------

def _test_source(source_type: str, source) -> dict:
    """Open the source once and read one frame, with a diagnosis a non-specialist can act on."""
    started = time.monotonic()
    steps = []
    if source_type == "network":
        probe = probe_tcp(source, settings.CAMERA_CONNECT_TEST_TIMEOUT)
        steps.append({"step": "network", "ok": probe["ok"], "message": probe.get("message") or f"Port {probe['port']} is reachable."})
        if not probe["ok"]:
            return {"ok": False, "steps": steps, "message": probe["message"], "elapsed_ms": int((time.monotonic() - started) * 1000)}
    reader = runtime.cameras.reader_factory("connection-test", source) if runtime.cameras else None
    if reader is None:
        raise HTTPException(status_code=503, detail="Camera services are not running.")
    try:
        if not reader.connect():
            msg = ("The stream could not be opened. Check the stream path (e.g. /Streaming/Channels/101), the user name and "
                   "password, and that RTSP is enabled on the camera or DVR.") if source_type == "network" else "The camera could not be opened."
            steps.append({"step": "open", "ok": False, "message": msg})
            return {"ok": False, "steps": steps, "message": msg, "elapsed_ms": int((time.monotonic() - started) * 1000)}
        steps.append({"step": "open", "ok": True, "message": "Stream opened."})
        frame = None
        for _ in range(20):
            frame = reader.read_frame()
            if frame is not None:
                break
            time.sleep(0.1)
        if frame is None:
            msg = "The stream opened but sent no video frames. The camera may be busy, or the codec is unsupported (try the sub-stream)."
            steps.append({"step": "frame", "ok": False, "message": msg})
            return {"ok": False, "steps": steps, "message": msg, "elapsed_ms": int((time.monotonic() - started) * 1000)}
        h, w = frame.shape[:2]
        steps.append({"step": "frame", "ok": True, "message": f"Received a {w}x{h} frame."})
        return {"ok": True, "steps": steps, "message": f"Connected: {w}x{h} video received.", "width": w, "height": h,
                "elapsed_ms": int((time.monotonic() - started) * 1000)}
    finally:
        reader.release()


@router.post("/{camera_id}/test")
async def test_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    cam = _get_camera(db, camera_id, user)
    if cam.source_type == "browser":
        return {"ok": True, "steps": [], "message": "Browser cameras connect when an operator starts them from Live Camera."}
    if runtime.cameras and runtime.cameras.worker(cam.id) is not None and cam.source_type == "device":
        raise HTTPException(status_code=409, detail="Stop the camera before testing a USB device (it can only be opened once).")
    try:
        if not cam.source_secret:
            raise SourceError("No source is configured for this camera.")
        source = resolve_source(cam.source_type, decrypt_source(cam.source_secret))
    except SourceError as exc:
        return {"ok": False, "steps": [{"step": "config", "ok": False, "message": str(exc)}], "message": str(exc)}
    result = await run_in_threadpool(_test_source, cam.source_type, source)
    record_audit(db, user, "camera.test", "camera", cam.id, {"ok": result["ok"]})
    db.commit()
    return result


@router.post("/test-source")
async def test_unsaved_source(body: SourceTest, admin: User = Depends(require_admin)):
    """Test a source before saving it (admins only; the same network policy applies)."""
    try:
        stored = validate_source(body.source_type, body.source)
        source = resolve_source(body.source_type, stored)
    except SourceError as exc:
        return {"ok": False, "steps": [{"step": "config", "ok": False, "message": str(exc)}], "message": str(exc)}
    return await run_in_threadpool(_test_source, body.source_type, source)


# -- counting line ----------------------------------------------------------------------------------

@router.put("/{camera_id}/line")
def set_line(camera_id: str, body: LineUpdate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    cam = _get_camera(db, camera_id, user)
    before = None if not cam.has_line else [cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2, cam.entry_side]
    cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2 = body.x1, body.y1, body.x2, body.y2
    cam.entry_side = body.entry_side
    cam.updated_at = utcnow()
    record_audit(db, user, "camera.line_update", "camera", cam.id, {"before": before, "after": [body.x1, body.y1, body.x2, body.y2, body.entry_side]})
    db.commit()
    if runtime.cameras:
        runtime.cameras.update_line(cam.id, line_from_camera(cam))
    return serialize_camera(cam, db)


@router.delete("/{camera_id}/line")
def clear_line(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    cam = _get_camera(db, camera_id, user)
    cam.line_x1 = cam.line_y1 = cam.line_x2 = cam.line_y2 = None
    cam.updated_at = utcnow()
    record_audit(db, user, "camera.line_clear", "camera", cam.id, {})
    db.commit()
    if runtime.cameras:
        runtime.cameras.update_line(cam.id, None)
    return serialize_camera(cam, db)


# -- zones ------------------------------------------------------------------------------------------

MAX_ZONES_PER_CAMERA = 12


@router.post("/{camera_id}/zones", status_code=201)
def create_zone(camera_id: str, body: ZoneBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id, admin)
    n = db.scalar(select(func.count()).select_from(CameraZone).where(CameraZone.camera_id == cam.id)) or 0
    if n >= MAX_ZONES_PER_CAMERA:
        raise HTTPException(status_code=409, detail=f"A camera can have at most {MAX_ZONES_PER_CAMERA} zones.")
    zone = CameraZone(
        organization_id=admin.organization_id, camera_id=cam.id, name=body.name, kind=body.kind,
        polygon=json.dumps(body.polygon), dwell_seconds=body.dwell_seconds, enabled=body.enabled,
    )
    db.add(zone)
    db.flush()
    record_audit(db, admin, "zone.create", "camera", cam.id, {"zone_id": zone.id, "name": zone.name, "kind": zone.kind, "dwell_seconds": zone.dwell_seconds})
    db.commit()
    if runtime.cameras:
        runtime.cameras.reload_zones(cam.id)
    return serialize_zone(zone)


@router.put("/{camera_id}/zones/{zone_id}")
def update_zone(camera_id: str, zone_id: int, body: ZoneBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id, admin)
    zone = get_owned(db, CameraZone, zone_id, admin, "Zone not found.")
    if zone.camera_id != cam.id:
        raise HTTPException(status_code=404, detail="Zone not found.")
    before = serialize_zone(zone)
    zone.name, zone.kind, zone.polygon = body.name, body.kind, json.dumps(body.polygon)
    zone.dwell_seconds, zone.enabled, zone.updated_at = body.dwell_seconds, body.enabled, utcnow()
    record_audit(db, admin, "zone.update", "camera", cam.id, {"zone_id": zone.id, "before": before, "after": serialize_zone(zone)})
    db.commit()
    if runtime.cameras:
        runtime.cameras.reload_zones(cam.id)
    return serialize_zone(zone)


@router.delete("/{camera_id}/zones/{zone_id}", status_code=204)
def delete_zone(camera_id: str, zone_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id, admin)
    zone = get_owned(db, CameraZone, zone_id, admin, "Zone not found.")
    if zone.camera_id != cam.id:
        raise HTTPException(status_code=404, detail="Zone not found.")
    record_audit(db, admin, "zone.delete", "camera", cam.id, {"zone_id": zone.id, "name": zone.name})
    db.delete(zone)
    db.commit()
    if runtime.cameras:
        runtime.cameras.reload_zones(cam.id)
    return Response(status_code=204)


@router.get("/{camera_id}/frame")
def get_camera_frame(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    """Latest frame received from a running camera (JPEG)."""
    _get_camera(db, camera_id, user)
    worker = runtime.cameras.worker(camera_id) if runtime.cameras else None
    jpeg = worker.latest_jpeg() if worker is not None and worker.status == "live" else None
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No live frame is available for this camera.")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
