"""Guard room: camera guards, the head guard's incidents and briefing, and the outgoing mail server."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin, require_operator
from config import settings
from db import get_db, utcnow
from models.entities import Camera, GuardIncident, User
from models.schemas import GuardAssignment, GuardPresetBody, HeadGuardConfigUpdate, IncidentAction, MailServerBody, MailTestBody
from runtime import runtime
from services import guards, head_guard, mail_server
from services.audit import record_audit
from services.site_settings import get_site_settings, local_day_bounds, site_zone
from services.tenancy import get_owned
from vision.detector import detector_availability

router = APIRouter(tags=["guards"])


def _status_of(camera_id: str):
    return runtime.cameras.status(camera_id) if runtime.cameras else None


def _today_start(db: Session, organization_id: int):
    row = get_site_settings(db, organization_id)
    return local_day_bounds(row, utcnow().astimezone(site_zone(row)).date())[0]


def _video_model_enabled() -> bool:
    return bool(runtime.anomaly and runtime.anomaly.health_check().get("enabled"))


# -- guard room ------------------------------------------------------------------------------------

@router.get("/guards/catalogue")
def catalogue(user: User = Depends(require_operator)):
    return guards.catalogue()


@router.get("/guard-room")
def guard_room(db: Session = Depends(get_db), user: User = Depends(require_operator)):
    org_id = user.organization_id
    roster = head_guard.roster(db, org_id, _status_of, _today_start(db, org_id))
    incidents = db.scalars(
        select(GuardIncident).where(
            GuardIncident.organization_id == org_id,
            (GuardIncident.status != "resolved") | (GuardIncident.last_seen_at >= utcnow() - timedelta(hours=24)),
        ).order_by(GuardIncident.status != "open", GuardIncident.last_seen_at.desc()).limit(40)
    ).all()
    open_count = sum(1 for i in incidents if i.status == "open")
    detector_ok = detector_availability()[0]
    config = head_guard.get_config(db, org_id)
    db.commit()  # get_site_settings may have created the settings row
    return {
        "summary": head_guard.summary_line(roster, open_count),
        "head_guard": {k: v for k, v in config.items() if k != "last_briefing"} | {"last_briefing": config.get("last_briefing")},
        "guards": roster,
        "incidents": [head_guard.serialize_incident(db, i) for i in incidents],
        "recommendations": head_guard.recommendations(db, org_id, roster, _video_model_enabled(), detector_ok),
        "capacity": {
            "max_cameras_per_server": settings.MAX_SIMULTANEOUS_STREAMS,
            "running": runtime.cameras.running_count(org_id) if runtime.cameras else 0,
            "video_model_enabled": _video_model_enabled(),
            "person_detector": detector_ok,
        },
    }


@router.put("/guards/{camera_id}")
def assign_guard(camera_id: str, body: GuardAssignment, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cam = get_owned(db, Camera, camera_id, admin, "Camera not found.")
    try:
        guards.assign(db, cam, body.guard_name, body.post, body.duties, body.reset_duties)
    except guards.GuardError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    cam.updated_at = utcnow()
    record_audit(db, admin, "guard.assign", "camera", cam.id, body.model_dump(exclude_none=True))
    db.commit()
    guards.invalidate(admin.organization_id)
    if runtime.cameras:
        runtime.cameras.set_fight_watch(cam.id, guards.watches_fights(cam))
    return next(g for g in head_guard.roster(db, admin.organization_id, _status_of, _today_start(db, admin.organization_id)) if g["camera_id"] == cam.id)


@router.post("/guards/assign")
def assign_posts(body: GuardPresetBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Bulk post assignment (duties reset to each post's defaults)."""
    cams = []
    for camera_id, post in body.assignments.items():
        cam = get_owned(db, Camera, camera_id, admin, f"Camera {camera_id} not found.")
        try:
            guards.assign(db, cam, None, post, None, reset_duties=True)
        except guards.GuardError as exc:
            raise HTTPException(status_code=422, detail=f"{camera_id}: {exc}")
        cams.append(cam)
    record_audit(db, admin, "guard.assign_bulk", "camera", None, {"assignments": body.assignments})
    db.commit()
    guards.invalidate(admin.organization_id)
    if runtime.cameras:
        for cam in cams:
            runtime.cameras.set_fight_watch(cam.id, guards.watches_fights(cam))
    return {"updated": len(cams)}


# -- head guard ------------------------------------------------------------------------------------

@router.get("/head-guard/config")
def get_head_guard(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return head_guard.get_config(db, admin.organization_id)


@router.put("/head-guard/config")
def update_head_guard(body: HeadGuardConfigUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    changes = body.model_dump(exclude_none=True)
    try:
        config = head_guard.save_config(db, admin.organization_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    record_audit(db, admin, "head_guard.update", "head_guard", None, changes)
    db.commit()
    return config


@router.post("/head-guard/briefing")
def send_briefing_now(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    n = head_guard.send_briefing(db, admin.organization_id, status_of=_status_of)
    if n == 0:
        raise HTTPException(status_code=409, detail="No enabled notification channel. Add email or Telegram under Settings → Notifications.")
    record_audit(db, admin, "head_guard.briefing", "head_guard", None, {"channels": n})
    db.commit()
    return {"queued": n}


@router.get("/head-guard/briefing/preview")
def preview_briefing(db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return {"text": head_guard.briefing_text(db, user.organization_id, utcnow(), _status_of)}


# -- incidents -------------------------------------------------------------------------------------

@router.get("/guard-incidents")
def list_incidents(status: str = Query("", pattern="^(|open|acknowledged|resolved)$"), limit: int = Query(50, ge=1, le=200),
                   db: Session = Depends(get_db), user: User = Depends(require_operator)):
    q = select(GuardIncident).where(GuardIncident.organization_id == user.organization_id)
    if status:
        q = q.where(GuardIncident.status == status)
    rows = db.scalars(q.order_by(GuardIncident.last_seen_at.desc()).limit(limit)).all()
    return [head_guard.serialize_incident(db, i) for i in rows]


@router.get("/guard-incidents/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return head_guard.serialize_incident(db, get_owned(db, GuardIncident, incident_id, user, "Incident not found."))


@router.post("/guard-incidents/{incident_id}")
def act_on_incident(incident_id: str, body: IncidentAction, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    incident = get_owned(db, GuardIncident, incident_id, user, "Incident not found.")
    try:
        head_guard.transition(db, incident, user.username, body.action, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    record_audit(db, user, f"incident.{body.action}", "guard_incident", incident.id, {"note": body.note} if body.note else {})
    db.commit()
    return head_guard.serialize_incident(db, incident)


# -- mail server -----------------------------------------------------------------------------------

@router.get("/mail-server")
def get_mail_server(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    data = mail_server.serialize(db, admin.organization_id)
    db.commit()
    return data


@router.put("/mail-server")
def put_mail_server(body: MailServerBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        mail_server.save_config(db, admin.organization_id, body.host, body.port, body.security, body.username,
                                body.password, body.from_address, body.from_name)
    except mail_server.MailError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Never log the password or username.
    record_audit(db, admin, "mail_server.update", "mail_server", None, {"host": body.host.strip(), "port": body.port, "security": body.security})
    db.commit()
    return mail_server.serialize(db, admin.organization_id)


@router.delete("/mail-server", status_code=204)
def delete_mail_server(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    mail_server.clear_config(db, admin.organization_id)
    record_audit(db, admin, "mail_server.delete", "mail_server", None, {})
    db.commit()
    return Response(status_code=204)


@router.post("/mail-server/test")
def test_mail_server(body: MailTestBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    to = body.to.strip().lower()
    if not mail_server.EMAIL.match(to):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    cfg = mail_server.effective_config(admin.organization_id)
    if cfg is None:
        raise HTTPException(status_code=409, detail="Save the mail server settings first.")
    try:
        mail_server.send(cfg, [to], "VIAHIND Vision test email",
                         f"This is a test email from VIAHIND Vision, sent by {admin.username}.\n\n"
                         f"Mail server: {cfg.host}:{cfg.port} ({cfg.security}). Incident reports from the head guard will arrive like this.")
    except mail_server.MailError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    record_audit(db, admin, "mail_server.test", "mail_server", None, {})
    db.commit()
    return {"sent": True, "via": f"{cfg.host}:{cfg.port}"}
