"""
Head guard: coordinates the camera guards (services/guards.py).

Every guard report (an alert raised on a camera) reaches the head guard, which

1. groups it with related reports into an incident: reports at the same location within the
   correlation window belong together, so a fight seen by the corridor guard and then the stair
   guard is one situation, not two separate emails;
2. raises the incident's severity one level when two or more guards report it (corroboration);
3. writes a plain-language summary and the next steps for the warden / owner (playbooks below);
4. escalates to the owner through the notification channels (email, Telegram, webhook) when an
   incident starts, gets more severe or another guard reports it, instead of one message per alert;
5. runs a daily briefing (shift report) and keeps a "what to do next" list for setup gaps.

Incidents are prompts for human follow-up. They never identify anyone or establish wrongdoing.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import session_scope, utcnow
from models.entities import (
    ALERT_SEVERITIES, OPEN_ALERT_STATUSES, Alert, Camera, CameraZone, DetectionEvent, GuardIncident, Location,
    NotificationChannel, NotificationDelivery,
)
from services.guards import DUTIES, duties_of, guard_display_name, post_of

logger = logging.getLogger("viahind.head_guard")

RANK = {s: i for i, s in enumerate(ALERT_SEVERITIES)}
OPEN_INCIDENT = ("open", "acknowledged")
SYSTEM_CATEGORIES = frozenset({"camera_health", "system"})
MAX_ACTIONS = 8

DEFAULT_CONFIG = {
    "enabled": True,              # head guard decides what reaches the owner (one message per incident)
    "correlation_minutes": 10,    # reports at one location within this window form one incident
    "corroboration_boost": True,  # +1 severity when two or more guards report the same incident
    "briefing_enabled": False,    # daily shift report to every channel
    "briefing_hour": 8,           # local hour (site timezone)
    "auto_resolve_minutes": 120,  # close quiet incidents whose reports are all closed
}

# Playbooks: what the head guard tells the warden to do for each kind of report.
PLAYBOOK: Dict[str, dict] = {
    "video_anomaly_model": {
        "headline": "Possible fight / altercation",
        "actions": [
            "Open the live view of {camera} now and check what is happening.",
            "If people are fighting, send the warden or nearest staff to {place} immediately; do not go alone.",
            "Check the snapshot before acting; the model can mistake play, hugging or crowding for a fight.",
            "If anyone is hurt or a weapon is visible, call 112 and the PG owner.",
        ],
    },
    "restricted_zone": {
        "headline": "Someone in a restricted area",
        "actions": [
            "Check the snapshot: is the person a resident, staff member or outsider?",
            "Ask the warden to visit {place} and politely ask the person to leave if they are not allowed there.",
            "If the area should be locked (terrace, store, roof), check the lock after the visit.",
        ],
    },
    "zone_dwell": {
        "headline": "Someone staying long in a watched area",
        "actions": [
            "Look at {camera}: is someone waiting, unwell, or loitering?",
            "Ask the warden to check on the person at {place}.",
        ],
    },
    "after_hours": {
        "headline": "Movement after curfew",
        "actions": [
            "Check the entry snapshot at {camera} and note who came in or went out late.",
            "Confirm the gate is locked; record the late entry in the register as per PG rules.",
        ],
    },
    "repeated_crossings": {
        "headline": "Repeated in-and-out at the gate",
        "actions": [
            "Watch {camera}: someone may be waiting at the door, or the camera may be miscounting.",
            "If the count looks wrong, adjust the counting line in Live Cameras.",
        ],
    },
    "traffic_frequency": {
        "headline": "Unusual rush at the gate",
        "actions": ["Check {camera} for a crowd or a group arriving together.", "Send staff to {place} if the crowd is unexpected."],
    },
    "occupancy": {
        "headline": "Too many people inside",
        "actions": ["Compare the headcount with the register; occupancy is an estimate.", "Check common areas for visitors or a gathering."],
    },
    "camera_offline": {
        "headline": "A guard cannot see (camera offline)",
        "actions": [
            "{place} is unguarded: check the camera's power and network cable / Wi-Fi.",
            "Restart the camera from Live Cameras once it is back.",
            "If the camera was unplugged on purpose, find out who did it.",
        ],
    },
    "camera_quality": {
        "headline": "A guard's view is blocked or dark",
        "actions": [
            "Check whether the camera at {place} is covered, moved, dirty or in the dark.",
            "Turn on the light or clean / re-aim the lens.",
        ],
    },
    "processing_error": {
        "headline": "Monitoring problem",
        "actions": ["Open Settings → System status and check the detector and database.", "Restart the service if the problem continues."],
    },
    "ml_anomaly": {
        "headline": "Unusual activity pattern",
        "actions": ["Compare this hour with a normal day in Reports; a statistical outlier is not a problem by itself."],
    },
}


# -- configuration -----------------------------------------------------------------------------

def get_config(db: Session, organization_id: int) -> dict:
    from services.site_settings import get_site_settings

    row = get_site_settings(db, organization_id)
    config = dict(DEFAULT_CONFIG)
    if row.head_guard_config:
        try:
            config.update({k: v for k, v in json.loads(row.head_guard_config).items() if k in DEFAULT_CONFIG or k == "last_briefing"})
        except (ValueError, TypeError):
            logger.warning("Invalid head guard configuration for organization %s; using defaults", organization_id)
    return config


def save_config(db: Session, organization_id: int, changes: dict) -> dict:
    """Validate and merge changes. Caller commits."""
    from services.site_settings import get_site_settings

    config = get_config(db, organization_id)
    for key, value in changes.items():
        if value is None:
            continue
        if key not in DEFAULT_CONFIG:
            raise ValueError(f"Unknown head guard setting '{key}'.")
        if isinstance(DEFAULT_CONFIG[key], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false.")
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be a whole number.")
            bounds = {"correlation_minutes": (1, 120), "briefing_hour": (0, 23), "auto_resolve_minutes": (10, 10080)}[key]
            if not bounds[0] <= value <= bounds[1]:
                raise ValueError(f"{key} must be between {bounds[0]} and {bounds[1]}.")
        config[key] = value
    get_site_settings(db, organization_id).head_guard_config = json.dumps(config, sort_keys=True)
    return config


# -- reports -> incidents ------------------------------------------------------------------------

def _bump(severity: str) -> str:
    return ALERT_SEVERITIES[min(RANK.get(severity, 0) + 1, len(ALERT_SEVERITIES) - 1)]


def _place(cam: Optional[Camera], zone_name: Optional[str]) -> str:
    if cam is None:
        return "the location"
    where = cam.location.strip() if cam.location and cam.location.strip() else cam.name
    return f"{where} ({zone_name})" if zone_name else where


def _actions_for(alert: Alert, cam: Optional[Camera], zone_name: Optional[str]) -> List[str]:
    book = PLAYBOOK.get(alert.rule_type)
    if not book:
        return ["Review the report on the Alerts page."]
    camera = cam.name if cam else "the camera"
    return [a.format(camera=camera, place=_place(cam, zone_name)) for a in book["actions"]]


def _headline(alert: Alert, cam: Optional[Camera]) -> str:
    book = PLAYBOOK.get(alert.rule_type)
    base = book["headline"] if book else alert.title
    return f"{base} at {cam.name}" if cam else base


def _merge(existing: List[str], new: Iterable[str], limit: int) -> List[str]:
    out = list(existing)
    for item in new:
        if item not in out:
            out.append(item)
    return out[:limit]


def on_report(db: Session, alert: Alert, created: bool, notify: bool) -> bool:
    """Handle one committed alert. Returns True when the head guard took over owner notifications
    (the caller then skips the per-alert channel queue). Never raises."""
    try:
        config = get_config(db, alert.organization_id)
        if not config["enabled"]:
            return False
        if alert.status not in OPEN_ALERT_STATUSES:
            return True
        _record(db, alert, created, notify, config)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Head guard could not process alert %s; falling back to direct notification", alert.id)
        return False


def _record(db: Session, alert: Alert, created: bool, notify: bool, config: dict) -> GuardIncident:
    now = utcnow()
    cam = db.get(Camera, alert.camera_id) if alert.camera_id else None
    zone = db.get(CameraZone, alert.zone_id) if alert.zone_id else None
    zone_name = zone.name if zone else None
    kind = "system" if alert.category in SYSTEM_CATEGORIES else "security"
    location_id = alert.location_id if alert.location_id is not None else (cam.location_id if cam else None)
    window = timedelta(minutes=int(config["correlation_minutes"]))

    query = select(GuardIncident).where(
        GuardIncident.organization_id == alert.organization_id,
        GuardIncident.kind == kind,
        GuardIncident.status.in_(OPEN_INCIDENT),
        GuardIncident.last_seen_at >= now - window,
    )
    query = query.where(GuardIncident.location_id == location_id) if location_id is not None else query.where(GuardIncident.location_id.is_(None))
    incident = db.scalar(query.order_by(GuardIncident.last_seen_at.desc()).limit(1))
    reporter = guard_display_name(cam) if cam else "Head guard"
    actions = _actions_for(alert, cam, zone_name)

    escalate = False
    if incident is None:
        incident = GuardIncident(
            id=str(uuid.uuid4()), organization_id=alert.organization_id, location_id=location_id, kind=kind,
            title=_headline(alert, cam)[:200], severity=alert.severity, status="open",
            summary=f"{reporter} reported: {alert.reason}", actions=json.dumps(actions),
            camera_ids=json.dumps([alert.camera_id] if alert.camera_id else []), alert_ids=json.dumps([alert.id]),
            report_count=1, first_seen_at=alert.first_seen_at or now, last_seen_at=now, created_at=now, updated_at=now,
        )
        db.add(incident)
        escalate = notify
    else:
        alert_ids = json.loads(incident.alert_ids or "[]")
        camera_ids = json.loads(incident.camera_ids or "[]")
        new_alert = alert.id not in alert_ids
        new_guard = bool(alert.camera_id) and alert.camera_id not in camera_ids
        if new_alert:
            alert_ids.append(alert.id)
            incident.summary = (incident.summary + f"\n{reporter} reported: {alert.reason}")[-4000:]
        if new_guard:
            camera_ids.append(alert.camera_id)
        incident.alert_ids = json.dumps(alert_ids[-200:])
        incident.camera_ids = json.dumps(camera_ids)
        incident.report_count += 1
        incident.last_seen_at = now
        incident.updated_at = now
        before = incident.severity
        if RANK.get(alert.severity, 0) > RANK.get(incident.severity, 0):
            incident.severity = alert.severity
            incident.title = _headline(alert, cam)[:200]
        if new_guard and kind == "security" and config["corroboration_boost"] and len(camera_ids) == 2:
            incident.severity = _bump(incident.severity)
            incident.summary += f"\nHead guard: {len(camera_ids)} guards reported this within {config['correlation_minutes']} minutes; treat it as an active situation."
            actions = [f"{len(camera_ids)} guards reported this: treat it as an active situation and send someone now."] + actions
        incident.actions = json.dumps(_merge(json.loads(incident.actions or "[]"), actions, MAX_ACTIONS))
        if incident.status == "acknowledged" and RANK[incident.severity] > RANK.get(before, 0):
            incident.status = "open"  # got worse after someone looked at it
        escalate = notify and (new_guard or RANK[incident.severity] > RANK.get(incident.escalated_severity or "info", 0) or new_alert and created)
    db.flush()
    if escalate:
        _escalate(db, incident, alert, reporter)
    return incident


def _wants(channel: NotificationChannel, severity: str, category: str) -> bool:
    if not channel.enabled or RANK.get(severity, 0) < RANK.get(channel.min_severity, 0):
        return False
    if channel.categories:
        try:
            return category in json.loads(channel.categories)
        except ValueError:
            return True
    return True


def incident_text(db: Session, incident: GuardIncident) -> str:
    from config import settings

    loc = db.get(Location, incident.location_id) if incident.location_id else None
    cams = [db.get(Camera, c) for c in json.loads(incident.camera_ids or "[]")]
    guards = ", ".join(guard_display_name(c) for c in cams if c is not None) or "Head guard"
    lines = [
        f"Situation: {incident.title}",
        f"Severity: {incident.severity.upper()} · Reports: {incident.report_count} · Guards: {guards}",
    ]
    if loc:
        lines.append(f"Location: {loc.name}")
    lines += ["", "What the guards saw:", incident.summary, "", "What to do next:"]
    lines += [f"  {i}. {a}" for i, a in enumerate(json.loads(incident.actions or "[]"), 1)]
    if settings.PUBLIC_BASE_URL:
        lines += ["", f"Open the guard room: {settings.PUBLIC_BASE_URL.rstrip('/')}/guards?incident={incident.id}"]
    lines += ["", "Automated report for human review. It does not identify anyone or prove wrongdoing."]
    return "\n".join(lines)


def _escalate(db: Session, incident: GuardIncident, alert: Alert, reporter: str) -> int:
    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == incident.organization_id)).all()
    text = incident_text(db, incident)
    subject = f"[{incident.severity.upper()}] {incident.title}"
    n = 0
    for channel in channels:
        if not _wants(channel, incident.severity, alert.category):
            continue
        db.add(NotificationDelivery(
            organization_id=incident.organization_id, alert_id=alert.id, channel_id=channel.id, kind="incident",
            subject=subject[:200], payload=json.dumps({"text": text, "incident_id": incident.id, "severity": incident.severity,
                                                       "reported_by": reporter, "alert_id": alert.id}),
            status="pending", next_attempt_at=utcnow(),
        ))
        n += 1
    incident.escalated_at = utcnow()
    incident.escalated_severity = incident.severity
    alert.last_notified_at = utcnow()
    return n


# -- review --------------------------------------------------------------------------------------

def transition(db: Session, incident: GuardIncident, username: str, action: str, note: Optional[str]) -> GuardIncident:
    now = utcnow()
    if action == "acknowledge":
        if incident.status != "open":
            raise ValueError("Only open incidents can be acknowledged.")
        incident.status, incident.acknowledged_by, incident.acknowledged_at = "acknowledged", username, now
    elif action == "resolve":
        if incident.status == "resolved":
            raise ValueError("The incident is already resolved.")
        incident.status, incident.resolved_by, incident.resolved_at = "resolved", username, now
        incident.resolution_note = (note or "").strip()[:2000] or None
    else:
        raise ValueError("Unknown action.")
    incident.updated_at = now
    return incident


def serialize_incident(db: Session, incident: GuardIncident) -> dict:
    cams = [db.get(Camera, c) for c in json.loads(incident.camera_ids or "[]")]
    loc = db.get(Location, incident.location_id) if incident.location_id else None
    alert_ids = json.loads(incident.alert_ids or "[]")
    snapshot_alert = db.scalar(
        select(Alert.id).where(Alert.id.in_(alert_ids), Alert.snapshot_status == "saved").order_by(Alert.last_seen_at.desc()).limit(1)
    ) if alert_ids else None
    return {
        "id": incident.id,
        "kind": incident.kind,
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "summary": incident.summary,
        "actions": json.loads(incident.actions or "[]"),
        "location_id": incident.location_id,
        "location_name": loc.name if loc else None,
        "guards": [{"camera_id": c.id, "camera_name": c.name, "guard_name": guard_display_name(c)} for c in cams if c is not None],
        "alert_ids": alert_ids,
        "snapshot_alert_id": snapshot_alert,
        "report_count": incident.report_count,
        "first_seen_at": incident.first_seen_at.isoformat(),
        "last_seen_at": incident.last_seen_at.isoformat(),
        "escalated_at": incident.escalated_at.isoformat() if incident.escalated_at else None,
        "acknowledged_by": incident.acknowledged_by,
        "acknowledged_at": incident.acknowledged_at.isoformat() if incident.acknowledged_at else None,
        "resolved_by": incident.resolved_by,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "resolution_note": incident.resolution_note,
    }


# -- situation board -----------------------------------------------------------------------------

GUARD_STATE = {"live": "on_duty", "connecting": "reporting_in", "stopped": "off_duty"}


def guard_state(status: Optional[dict], cam: Camera) -> str:
    if not cam.enabled:
        return "disabled"
    if status is None:
        return "off_duty"
    return GUARD_STATE.get(status.get("status"), "unreachable")


def roster(db: Session, organization_id: int, status_of, since: datetime) -> List[dict]:
    """One entry per camera guard. status_of(camera_id) -> worker snapshot dict or None."""
    cams = db.scalars(select(Camera).where(Camera.organization_id == organization_id).order_by(Camera.name)).all()
    counts = dict(db.execute(
        select(Alert.camera_id, func.count()).where(Alert.organization_id == organization_id, Alert.first_seen_at >= since,
                                                    Alert.camera_id.is_not(None)).group_by(Alert.camera_id)
    ).all())
    out = []
    for cam in cams:
        status = status_of(cam.id)
        last = db.execute(
            select(Alert.title, Alert.severity, Alert.last_seen_at).where(Alert.camera_id == cam.id).order_by(Alert.last_seen_at.desc()).limit(1)
        ).first()
        post = post_of(cam)
        duties = sorted(duties_of(cam), key=list(DUTIES).index)
        out.append({
            "camera_id": cam.id,
            "camera_name": cam.name,
            "position": cam.location,
            "location_id": cam.location_id,
            "guard_name": guard_display_name(cam),
            "custom_name": cam.guard_name,
            "post": post.key,
            "post_label": post.label,
            "duties": duties,
            "custom_duties": cam.guard_duties is not None,
            "state": guard_state(status, cam),
            "status_message": (status or {}).get("message", ""),
            "tracked_people": (status or {}).get("tracked_people", 0),
            "fps": (status or {}).get("fps", 0.0),
            "detection_status": (status or {}).get("detection_status", "off"),
            "reports_today": counts.get(cam.id, 0),
            "last_report": {"title": last[0], "severity": last[1], "at": last[2].isoformat()} if last else None,
            "has_line": cam.has_line,
        })
    return out


def recommendations(db: Session, organization_id: int, guards: List[dict], video_model_enabled: bool, detector_ok: bool) -> List[dict]:
    """The head guard's "what to do next" list, most urgent first."""
    from services.mail_server import is_configured as mail_configured
    from services.business_hours import parse_hours

    recs: List[dict] = []
    open_incidents = db.scalars(select(GuardIncident).where(
        GuardIncident.organization_id == organization_id, GuardIncident.status == "open"
    ).order_by(GuardIncident.last_seen_at.desc()).limit(3)).all()
    for inc in open_incidents:
        recs.append({"priority": "urgent" if RANK[inc.severity] >= RANK["high"] else "high",
                     "text": f"Check and acknowledge: {inc.title}", "link": f"/guards?incident={inc.id}"})
    cams = {c.id: c for c in db.scalars(select(Camera).where(Camera.organization_id == organization_id))}
    zones: Dict[str, List[str]] = {}
    for z in db.scalars(select(CameraZone).where(CameraZone.organization_id == organization_id, CameraZone.enabled.is_(True))):
        zones.setdefault(z.camera_id, []).append(z.kind)
    for g in guards:
        cam = cams.get(g["camera_id"])
        if cam is None or g["state"] == "disabled":
            continue
        if g["state"] == "unreachable":
            recs.append({"priority": "urgent", "text": f"{g['guard_name']} cannot see: {g['status_message'] or 'camera not delivering video'}. Check power and network.", "link": "/live"})
        elif g["state"] == "off_duty":
            recs.append({"priority": "high", "text": f"{g['guard_name']} is off duty. Start {cam.name} in Live Cameras so {g['post_label'].lower()} is watched.", "link": "/live"})
        duties = set(g["duties"])
        if duties & {"gate_log", "crowding", "curfew"} and not cam.has_line:
            recs.append({"priority": "medium", "text": f"Draw the counting line on {cam.name}; the gate log and curfew watch need it.", "link": "/live"})
        if "restricted" in duties and "restricted" not in zones.get(cam.id, []):
            recs.append({"priority": "medium", "text": f"Mark the restricted area on {cam.name} (Live Cameras → Zones) so its guard knows what to protect.", "link": "/live"})
        if "loitering" in duties and not zones.get(cam.id):
            recs.append({"priority": "low", "text": f"Add a monitored zone on {cam.name} for loitering watch.", "link": "/live"})
        if "curfew" in duties:
            loc = db.get(Location, cam.location_id)
            if loc is not None and parse_hours(loc.business_hours) is None:
                recs.append({"priority": "medium", "text": f"Set the gate timings (curfew) for {loc.name} under Settings → Locations.", "link": "/settings#locations"})
    if any("fight" in g["duties"] and g["state"] == "on_duty" for g in guards) and not video_model_enabled:
        recs.append({"priority": "high", "text": "Fight watch is assigned but the video anomaly model is turned off (ANOMALY_DETECTION_ENABLED).", "link": "/settings#video-anomaly"})
    if guards and not detector_ok:
        recs.append({"priority": "urgent", "text": "Person detection is not available, so guards cannot see people. Set PERSON_MODEL_PATH.", "link": "/settings#integrations"})
    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == organization_id, NotificationChannel.enabled.is_(True))).all()
    if not channels:
        recs.append({"priority": "high", "text": "No one is told about incidents. Add the owner's email or Telegram under Settings → Notifications.", "link": "/settings#notifications"})
    elif any(c.kind == "email" for c in channels) and not mail_configured(db, organization_id):
        recs.append({"priority": "high", "text": "An email channel exists but no mail server is set. Configure it under Settings → Notifications → Mail server.", "link": "/settings#mail-server"})
    if not guards:
        recs.append({"priority": "high", "text": "No guards yet. Add your cameras (up to 16 per server) under Settings → Cameras.", "link": "/settings#cameras"})
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: order[r["priority"]])
    return recs[:12]


def summary_line(guards: List[dict], open_count: int) -> str:
    on = sum(1 for g in guards if g["state"] == "on_duty")
    total = sum(1 for g in guards if g["state"] != "disabled")
    if not total:
        return "No guards are posted yet."
    if open_count:
        return f"{on} of {total} guards on duty · {open_count} open incident(s) need attention."
    if on < total:
        return f"{on} of {total} guards on duty · {total - on} post(s) unguarded."
    return f"All {total} guards on duty · all quiet."


# -- periodic work: auto-resolve and the daily briefing -------------------------------------------

def tick(now: Optional[datetime] = None) -> None:
    from models.entities import Organization

    now = now or utcnow()
    with session_scope() as db:
        org_ids = list(db.scalars(select(Organization.id).where(Organization.is_active.is_(True))))
    for org_id in org_ids:
        try:
            with session_scope() as db:
                config = get_config(db, org_id)
                if not config["enabled"]:
                    continue
                _auto_resolve(db, org_id, config, now)
                if config["briefing_enabled"]:
                    _maybe_brief(db, org_id, config, now)
        except Exception:
            logger.exception("Head guard tick failed for organization %s", org_id)


def _auto_resolve(db: Session, org_id: int, config: dict, now: datetime) -> None:
    quiet = now - timedelta(minutes=int(config["auto_resolve_minutes"]))
    for inc in db.scalars(select(GuardIncident).where(
        GuardIncident.organization_id == org_id, GuardIncident.status.in_(OPEN_INCIDENT), GuardIncident.last_seen_at < quiet
    )):
        ids = json.loads(inc.alert_ids or "[]")
        still_open = db.scalar(select(func.count()).select_from(Alert).where(Alert.id.in_(ids), Alert.status.in_(OPEN_ALERT_STATUSES))) if ids else 0
        if not still_open:
            inc.status, inc.resolved_by, inc.resolved_at = "resolved", "head guard", now
            inc.resolution_note = "All reports were closed and nothing new happened; resolved automatically."
            inc.updated_at = now


def _maybe_brief(db: Session, org_id: int, config: dict, now: datetime) -> None:
    from services.site_settings import get_site_settings, site_zone

    local = now.astimezone(site_zone(get_site_settings(db, org_id)))
    today = local.strftime("%Y-%m-%d")
    if local.hour != int(config["briefing_hour"]) or config.get("last_briefing") == today:
        return
    send_briefing(db, org_id, now)
    stored = get_config(db, org_id)
    stored["last_briefing"] = today
    get_site_settings(db, org_id).head_guard_config = json.dumps(stored, sort_keys=True)


def briefing_text(db: Session, org_id: int, now: datetime, status_of=lambda _id: None) -> str:
    since = now - timedelta(hours=24)
    guards = roster(db, org_id, status_of, since)
    incidents = db.scalars(select(GuardIncident).where(GuardIncident.organization_id == org_id, GuardIncident.first_seen_at >= since)).all()
    open_now = db.scalar(select(func.count()).select_from(GuardIncident).where(
        GuardIncident.organization_id == org_id, GuardIncident.status.in_(OPEN_INCIDENT))) or 0
    entries = dict(db.execute(select(DetectionEvent.event_type, func.count()).where(
        DetectionEvent.organization_id == org_id, DetectionEvent.occurred_at >= since,
        DetectionEvent.event_type.in_(("entry", "exit")), DetectionEvent.review_status != "rejected",
    ).group_by(DetectionEvent.event_type)).all())
    by_sev: Dict[str, int] = {}
    for inc in incidents:
        by_sev[inc.severity] = by_sev.get(inc.severity, 0) + 1
    lines = ["Head guard · daily briefing (last 24 hours)", "",
             f"Gate log: {entries.get('entry', 0)} entries, {entries.get('exit', 0)} exits.",
             f"Incidents: {len(incidents)}" + (f" ({', '.join(f'{n} {s}' for s, n in sorted(by_sev.items(), key=lambda kv: -RANK[kv[0]]))})" if by_sev else "") + f" · still open: {open_now}."]
    if incidents:
        lines += ["", "Incidents:"]
        lines += [f"  - [{i.severity.upper()}] {i.title} · {i.report_count} report(s) · {i.status}" for i in incidents[:15]]
    lines += ["", "Guards:"]
    for g in guards:
        lines.append(f"  - {g['guard_name']} ({g['post_label']}): {g['reports_today']} report(s)")
    lines += ["", "Automated summary for the owner. Reports need human review and never identify anyone."]
    return "\n".join(lines)


def send_briefing(db: Session, org_id: int, now: Optional[datetime] = None, status_of=lambda _id: None) -> int:
    from services.notifications import queue_message

    now = now or utcnow()
    text = briefing_text(db, org_id, now, status_of)
    n = 0
    for channel in db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == org_id, NotificationChannel.enabled.is_(True))):
        queue_message(db, channel, "briefing", "Head guard daily briefing", {"text": text})
        n += 1
    return n
