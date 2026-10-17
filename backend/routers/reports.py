"""Footfall and operations reports from stored events (JSON and CSV)."""

import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import require_viewer
from db import get_db
from models.entities import User
from services.audit import record_audit
from services.stats import period_report
from services.tenancy import owned_camera, owned_location

router = APIRouter(prefix="/reports", tags=["reports"])


def _report(db: Session, user: User, date_from: date, date_to: date, location_id: Optional[int], camera_id: Optional[str]) -> dict:
    owned_location(db, user, location_id)
    owned_camera(db, user, camera_id)
    try:
        return period_report(db, user.organization_id, date_from, date_to, location_id, camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/summary")
def summary(
    date_from: date,
    date_to: date,
    location_id: Optional[int] = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    return _report(db, user, date_from, date_to, location_id, camera_id)


@router.get("/export.csv")
def export_report(
    date_from: date,
    date_to: date,
    section: str = Query("daily", pattern="^(daily|hourly|cameras|locations)$"),
    location_id: Optional[int] = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    report = _report(db, user, date_from, date_to, location_id, camera_id)
    record_audit(db, user, "report.export", "report", section, {"date_from": date_from, "date_to": date_to,
                                                                 "location_id": location_id, "camera_id": camera_id})
    db.commit()
    buf = io.StringIO()
    w = csv.writer(buf)
    if section == "daily":
        w.writerow(["date", "entries", "exits", "uncertain"])
        for d in report["daily"]:
            w.writerow([d["date"], d["entries"], d["exits"], d["uncertain"]])
    elif section == "hourly":
        w.writerow(["hour_of_day", "entries", "exits"])
        for h in report["hourly"]:
            w.writerow([f"{h['hour']:02d}:00", h["entries"], h["exits"]])
    elif section == "cameras":
        w.writerow(["camera", "entries", "exits", "uncertain"])
        for c in report["cameras"]:
            w.writerow([_safe(c["camera_name"]), c["entries"], c["exits"], c["uncertain"]])
    else:
        w.writerow(["location", "entries", "exits", "uncertain"])
        for loc in report["locations"]:
            w.writerow([_safe(loc["location_name"]), loc["entries"], loc["exits"], loc["uncertain"]])
    filename = f"viahind-{section}-{date_from}-{date_to}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})


def _safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
