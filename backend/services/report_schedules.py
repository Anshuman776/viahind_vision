"""Scheduled reports: after each completed period (day, Monday-Sunday week, calendar month) a summary
is queued to the schedule's notification channel. Delivery, retries and rate limits are those of
the notification service; images and personal labels are never included."""

import logging
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import session_scope, utcnow
from models.entities import Location, NotificationChannel, ReportSchedule
from services.notifications import queue_message
from services.site_settings import get_site_settings, site_zone
from services.stats import period_report

logger = logging.getLogger("viahind.reports")

FREQUENCIES = ("daily", "weekly", "monthly")


def last_complete_period(frequency: str, today: date) -> Tuple[date, date]:
    if frequency == "daily":
        d = today - timedelta(days=1)
        return d, d
    if frequency == "weekly":
        end = today - timedelta(days=today.weekday() + 1)  # last Sunday
        return end - timedelta(days=6), end
    if frequency == "monthly":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    raise ValueError("Unknown frequency.")


def report_text(name: str, location_name: Optional[str], report: dict) -> str:
    t, c = report["totals"], report["comparison"]

    def change(v):
        return "n/a" if v is None else f"{v:+.1f}%"

    lines = [
        f"{name} — {report['date_from']} to {report['date_to']} ({report['timezone']})",
        f"Location: {location_name or 'All locations'}",
        "",
        f"Footfall (entries): {t['entries']}  ({change(c['entries_change_pct'])} vs previous period)",
        f"Exits: {t['exits']}  ({change(c['exits_change_pct'])})",
        f"Average daily footfall: {t['avg_daily_footfall']}",
        f"Unclassified crossings awaiting review: {t['uncertain']}",
    ]
    if report["peak_hours"]:
        lines.append("Peak hours: " + ", ".join(f"{h['hour']:02d}:00 ({h['entries']})" for h in report["peak_hours"]))
    if report["cameras"]:
        lines += ["", "By camera:"] + [f"  {cam['camera_name']}: {cam['entries']} in / {cam['exits']} out" for cam in report["cameras"][:10]]
    a = report["alerts"]
    lines += ["", f"Alerts raised: {a['total']}" + (" (" + ", ".join(f"{k}: {v}" for k, v in sorted(a["by_severity"].items())) + ")" if a["total"] else "")]
    lines += ["", "Figures are counts of line crossings recorded by the cameras; they can be affected by camera "
              "outages, occlusion and uncounted entrances."]
    return "\n".join(lines)


def send_schedule(db: Session, schedule: ReportSchedule, period: Tuple[date, date]) -> None:
    channel = db.get(NotificationChannel, schedule.channel_id)
    if channel is None or channel.organization_id != schedule.organization_id:
        raise ValueError("The schedule's channel no longer exists.")
    report = period_report(db, schedule.organization_id, period[0], period[1], location_id=schedule.location_id)
    location = db.get(Location, schedule.location_id) if schedule.location_id else None
    text = report_text(schedule.name, location.name if location else None, report)
    payload = {"text": text, "report": {k: report[k] for k in ("date_from", "date_to", "timezone", "totals", "comparison", "peak_hours", "daily", "alerts")}}
    queue_message(db, channel, "report", f"{schedule.name}: {period[0]} to {period[1]}", payload)


def run_due_schedules(now: Optional[datetime] = None) -> int:
    now = now or utcnow()
    sent = 0
    with session_scope() as db:
        ids = list(db.scalars(select(ReportSchedule.id).where(ReportSchedule.enabled.is_(True))))
    for schedule_id in ids:
        try:
            with session_scope() as db:
                schedule = db.get(ReportSchedule, schedule_id)
                today = now.astimezone(site_zone(get_site_settings(db, schedule.organization_id))).date()
                period = last_complete_period(schedule.frequency, today)
                if schedule.last_period_end == period[1].isoformat():
                    continue
                send_schedule(db, schedule, period)
                schedule.last_period_end = period[1].isoformat()
                schedule.last_run_at = utcnow()
                sent += 1
        except Exception:
            logger.exception("Scheduled report %s failed", schedule_id)
    return sent


def serialize_schedule(row: ReportSchedule) -> dict:
    return {
        "id": row.id, "name": row.name, "frequency": row.frequency, "location_id": row.location_id,
        "channel_id": row.channel_id, "enabled": row.enabled, "last_period_end": row.last_period_end,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
    }
