"""
Camera inventory, lifecycle and entrance-line configuration.

Replaces the earlier in-memory list of hardcoded "online" cameras: cameras are now persisted,
and their status comes from the running worker (Live only while frames actually arrive).
Camera sources are write-only; responses only include a masked description.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_admin, require_operator
from db import get_db, utcnow
from models.entities import Camera, DetectionEvent, User
from models.schemas import CameraCreate, CameraUpdate, LineUpdate
from runtime import runtime
from services.audit import record_audit
from vision.camera_manager import line_from_camera
from vision.sources import SourceError, decrypt_source, encrypt_source, mask_source, validate_source

router = APIRouter(prefix="/cameras", tags=["cameras"])


def serialize_camera(cam: Camera) -> dict:
    try:
        source = decrypt_source(cam.source_secret) if cam.source_secret else None
        source_description = mask_source(cam.source_type, source)
    except SourceError as exc:
        source_description = str(exc)
    status = runtime.cameras.status(cam.id) if runtime.cameras else {"status": "stopped"}
    return {
        "id": cam.id,
        "name": cam.name,
        "location": cam.location,
        "source_type": cam.source_type,
        "source_description": source_description,
        "source_configured": cam.source_type == "browser" or bool(cam.source_secret),
        "enabled": cam.enabled,
        "detection_enabled": cam.detection_enabled,
        "desired_running": cam.desired_running,
        "line": None
        if not cam.has_line
        else {"x1": cam.line_x1, "y1": cam.line_y1, "x2": cam.line_x2, "y2": cam.line_y2, "entry_side": cam.entry_side},
        "runtime": status,
    }


def _get_camera(db: Session, camera_id: str) -> Camera:
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return cam


@router.get("")
def list_cameras(db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return [serialize_camera(c) for c in db.scalars(select(Camera).order_by(Camera.name))]


@router.get("/{camera_id}")
def get_camera(camera_id: str, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return serialize_camera(_get_camera(db, camera_id))


@router.post("", status_code=201)
def create_camera(body: CameraCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.get(Camera, body.id) is not None:
        raise HTTPException(status_code=409, detail="A camera with this ID already exists.")
    try:
        source = validate_source(body.source_type, body.source)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    cam = Camera(
        id=body.id,
        name=body.name,
        location=body.location,
        source_type=body.source_type,
        source_secret=encrypt_source(source) if source else None,
        detection_enabled=body.detection_enabled,
    )
    db.add(cam)
    record_audit(db, admin, "camera.create", "camera", cam.id, {"name": cam.name, "source_type": cam.source_type})
    db.commit()
    return serialize_camera(cam)


@router.patch("/{camera_id}")
def update_camera(camera_id: str, body: CameraUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id)
    changes = {}
    for field in ("name", "location", "enabled", "detection_enabled"):
        value = getattr(body, field)
        if value is not None and value != getattr(cam, field):
            changes[field] = [getattr(cam, field), value]
            setattr(cam, field, value.strip() if isinstance(value, str) else value)
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
    restart = runtime.cameras and runtime.cameras.worker(cam.id) is not None
    if restart and ("source" in changes or "detection_enabled" in changes or changes.get("enabled") == [True, False]):
        if cam.enabled:
            try:
                runtime.cameras.start(cam.id)
            except SourceError:
                runtime.cameras.stop(cam.id)
        else:
            runtime.cameras.stop(cam.id)
    return serialize_camera(cam)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = _get_camera(db, camera_id)
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
    cam = _get_camera(db, camera_id)
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
    return serialize_camera(cam)


@router.post("/{camera_id}/start")
def start_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _lifecycle(camera_id, db, user, "start")


@router.post("/{camera_id}/stop")
def stop_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _lifecycle(camera_id, db, user, "stop")


@router.post("/{camera_id}/reconnect")
def reconnect_camera(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _lifecycle(camera_id, db, user, "reconnect")


@router.put("/{camera_id}/line")
def set_line(camera_id: str, body: LineUpdate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    cam = _get_camera(db, camera_id)
    before = None if not cam.has_line else [cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2, cam.entry_side]
    cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2 = body.x1, body.y1, body.x2, body.y2
    cam.entry_side = body.entry_side
    cam.updated_at = utcnow()
    record_audit(db, user, "camera.line_update", "camera", cam.id, {"before": before, "after": [body.x1, body.y1, body.x2, body.y2, body.entry_side]})
    db.commit()
    if runtime.cameras:
        runtime.cameras.update_line(cam.id, line_from_camera(cam))
    return serialize_camera(cam)


@router.delete("/{camera_id}/line")
def clear_line(camera_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    cam = _get_camera(db, camera_id)
    cam.line_x1 = cam.line_y1 = cam.line_x2 = cam.line_y2 = None
    cam.updated_at = utcnow()
    record_audit(db, user, "camera.line_clear", "camera", cam.id, {})
    db.commit()
    if runtime.cameras:
        runtime.cameras.update_line(cam.id, None)
    return serialize_camera(cam)


@router.get("/{camera_id}/frame")
def get_camera_frame(camera_id: str, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    """Latest frame received from a running camera (JPEG)."""
    _get_camera(db, camera_id)
    worker = runtime.cameras.worker(camera_id) if runtime.cameras else None
    jpeg = worker.latest_jpeg() if worker is not None and worker.status == "live" else None
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No live frame is available for this camera.")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
