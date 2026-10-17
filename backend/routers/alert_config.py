"""Alert rule configuration, notification channels, delivery log and scheduled reports (administrators)."""

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin
from db import get_db, utcnow
from models.entities import NotificationChannel, NotificationDelivery, ReportSchedule, User
from models.schemas import ChannelBody, ChannelUpdate, RuleUpdate, ScheduleBody
from services.alert_engine import invalidate_rules
from services.alert_rules import CATEGORIES, RULES, save_rule, serialize_rules
from services.audit import record_audit
from services.notifications import ChannelError, build_config, channel_config, queue_message, serialize_channel, serialize_delivery, store_config
from services.report_schedules import last_complete_period, send_schedule, serialize_schedule
from services.secretbox import SecretError
from services.site_settings import get_site_settings, site_zone
from services.tenancy import get_owned, owned_location

router = APIRouter(tags=["alert configuration"])


# -- rules -----------------------------------------------------------------------------------------

@router.get("/alert-rules")
def list_rules(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return serialize_rules(db, admin.organization_id)


@router.put("/alert-rules/{rule_type}")
def update_rule(rule_type: str, body: RuleUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if rule_type not in RULES:
        raise HTTPException(status_code=404, detail="Rule not found.")
    try:
        save_rule(db, admin.organization_id, rule_type, body.enabled, body.severity, body.cooldown_seconds, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    record_audit(db, admin, "alert_rule.update", "alert_rule", rule_type, body.model_dump(exclude_none=True))
    db.commit()
    invalidate_rules(admin.organization_id)
    return next(r for r in serialize_rules(db, admin.organization_id) if r["rule_type"] == rule_type)


# -- channels --------------------------------------------------------------------------------------

def _categories(values):
    if values is None:
        return None
    unknown = [v for v in values if v not in CATEGORIES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown categories: {', '.join(unknown)}")
    return json.dumps(sorted(set(values))) if values else None


@router.get("/notification-channels")
def list_channels(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == admin.organization_id).order_by(NotificationChannel.name))
    return [serialize_channel(c) for c in rows]


@router.post("/notification-channels", status_code=201)
def create_channel(body: ChannelBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        config = build_config(body.kind, body.recipients, body.url, body.secret, bot_token=body.bot_token,
                              chat_id=body.chat_id, attach_snapshot=body.attach_snapshot)
    except ChannelError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    channel = NotificationChannel(
        organization_id=admin.organization_id, kind=body.kind, name=body.name.strip(), enabled=body.enabled,
        min_severity=body.min_severity, categories=_categories(body.categories), rate_limit_per_hour=body.rate_limit_per_hour,
        config_secret="",
    )
    store_config(channel, config)
    db.add(channel)
    db.flush()
    record_audit(db, admin, "channel.create", "notification_channel", channel.id, {"kind": channel.kind, "name": channel.name})
    db.commit()
    return serialize_channel(channel)


@router.patch("/notification-channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    channel = get_owned(db, NotificationChannel, channel_id, admin, "Channel not found.")
    changes = {}
    for field in ("name", "enabled", "min_severity", "rate_limit_per_hour"):
        value = getattr(body, field)
        if value is not None and value != getattr(channel, field):
            changes[field] = [getattr(channel, field), value]
            setattr(channel, field, value.strip() if isinstance(value, str) else value)
    if body.clear_categories:
        channel.categories, changes["categories"] = None, "cleared"
    elif body.categories is not None:
        channel.categories, changes["categories"] = _categories(body.categories), body.categories
    if any(v is not None for v in (body.recipients, body.url, body.secret, body.bot_token, body.chat_id, body.attach_snapshot)):
        try:
            existing = channel_config(channel)
        except SecretError:
            existing = {}
        try:
            store_config(channel, build_config(channel.kind, body.recipients, body.url, body.secret, existing,
                                               bot_token=body.bot_token, chat_id=body.chat_id, attach_snapshot=body.attach_snapshot))
        except ChannelError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        changes["configuration"] = "replaced"  # never log recipients, URLs or secrets
    channel.updated_at = utcnow()
    if changes:
        record_audit(db, admin, "channel.update", "notification_channel", channel.id, changes)
    db.commit()
    return serialize_channel(channel)


@router.delete("/notification-channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    channel = get_owned(db, NotificationChannel, channel_id, admin, "Channel not found.")
    record_audit(db, admin, "channel.delete", "notification_channel", channel.id, {"name": channel.name})
    db.delete(channel)
    db.commit()
    return Response(status_code=204)


@router.post("/notification-channels/{channel_id}/test")
def test_channel(channel_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Queue a test message; its delivery status appears in the delivery log within seconds."""
    channel = get_owned(db, NotificationChannel, channel_id, admin, "Channel not found.")
    row = queue_message(db, channel, "test", "VIAHIND Vision test notification",
                        {"text": f"Test notification for channel '{channel.name}', requested by {admin.username}."})
    record_audit(db, admin, "channel.test", "notification_channel", channel.id, {})
    db.commit()
    return serialize_delivery(row)


@router.get("/notification-deliveries")
def list_deliveries(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.scalars(select(NotificationDelivery).where(NotificationDelivery.organization_id == admin.organization_id)
                      .order_by(NotificationDelivery.id.desc()).limit(limit))
    return [serialize_delivery(r) for r in rows]


# -- scheduled reports -----------------------------------------------------------------------------

@router.get("/report-schedules")
def list_schedules(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.scalars(select(ReportSchedule).where(ReportSchedule.organization_id == admin.organization_id).order_by(ReportSchedule.name))
    return [serialize_schedule(r) for r in rows]


@router.post("/report-schedules", status_code=201)
def create_schedule(body: ScheduleBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    get_owned(db, NotificationChannel, body.channel_id, admin, "Channel not found.")
    owned_location(db, admin, body.location_id)
    tz = site_zone(get_site_settings(db, admin.organization_id))
    from datetime import datetime

    # Start with the next period: do not immediately send the period that just ended.
    current_end = last_complete_period(body.frequency, datetime.now(tz).date())[1]
    row = ReportSchedule(
        organization_id=admin.organization_id, name=body.name.strip(), frequency=body.frequency, location_id=body.location_id,
        channel_id=body.channel_id, enabled=body.enabled, last_period_end=current_end.isoformat(),
    )
    db.add(row)
    db.flush()
    record_audit(db, admin, "report_schedule.create", "report_schedule", row.id, {"name": row.name, "frequency": row.frequency})
    db.commit()
    return serialize_schedule(row)


@router.delete("/report-schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    row = get_owned(db, ReportSchedule, schedule_id, admin, "Schedule not found.")
    record_audit(db, admin, "report_schedule.delete", "report_schedule", row.id, {"name": row.name})
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/report-schedules/{schedule_id}/send")
def send_schedule_now(schedule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Send the most recent complete period now (does not change the schedule)."""
    row = get_owned(db, ReportSchedule, schedule_id, admin, "Schedule not found.")
    from datetime import datetime

    tz = site_zone(get_site_settings(db, admin.organization_id))
    period = last_complete_period(row.frequency, datetime.now(tz).date())
    try:
        send_schedule(db, row, period)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    record_audit(db, admin, "report_schedule.send", "report_schedule", row.id, {"period": [period[0], period[1]]})
    db.commit()
    return {"queued": True, "period": [period[0].isoformat(), period[1].isoformat()]}
