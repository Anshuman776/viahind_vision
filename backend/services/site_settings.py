"""Organization settings: the operational settings record and derived detection parameters."""

from datetime import datetime, time, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.entities import SiteSettings
from vision.line_crossing import CrossingParams


def get_site_settings(db: Session, organization_id: int) -> SiteSettings:
    row = db.scalar(select(SiteSettings).where(SiteSettings.organization_id == organization_id))
    if row is None:
        row = SiteSettings(organization_id=organization_id, site_name=settings.ACTIVE_FACILITY_NAME, timezone=_valid_tz(settings.SITE_TIMEZONE))
        db.add(row)
        db.flush()
    return row


def _valid_tz(name: str) -> str:
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def site_zone(row: SiteSettings) -> ZoneInfo:
    try:
        return ZoneInfo(row.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_day_bounds(row: SiteSettings, day) -> Tuple[datetime, datetime]:
    """UTC-aware [start, end) of a calendar day in the site timezone (DST-safe)."""
    tz = site_zone(row)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def crossing_params(row: SiteSettings) -> CrossingParams:
    return CrossingParams(
        min_confidence=row.min_confidence,
        cooldown_seconds=row.cooldown_seconds,
        track_timeout_seconds=row.track_timeout_seconds,
        min_track_hits=row.min_track_hits,
        min_side_frames=row.min_side_frames,
        band=row.line_band,
        anchor=row.anchor_point,
    )


def format_person_label(number: int) -> str:
    return f"Unknown Person {number:02d}"


def allocate_person_label(db: Session, organization_id: int) -> str:
    """Next pseudonymous label, unique within the organization. Caller commits."""
    row = get_site_settings(db, organization_id)
    number = row.next_person_number
    row.next_person_number = number + 1
    return format_person_label(number)
