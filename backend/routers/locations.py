"""Business locations (premises) of an organization: capacity and business hours."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_admin, require_viewer
from db import get_db, utcnow
from models.entities import Camera, Location, User
from models.schemas import LocationBody, LocationUpdate
from services.audit import record_audit
from services.business_hours import parse_hours, validate_hours
from services.tenancy import get_owned

router = APIRouter(prefix="/locations", tags=["locations"])


def serialize_location(loc: Location, db: Session) -> dict:
    cameras = db.scalar(select(func.count()).select_from(Camera).where(Camera.location_id == loc.id)) or 0
    return {
        "id": loc.id, "name": loc.name, "address": loc.address, "capacity": loc.capacity,
        "business_hours": parse_hours(loc.business_hours), "is_active": loc.is_active, "camera_count": cameras,
    }


def _hours(value):
    try:
        return validate_hours(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("")
def list_locations(db: Session = Depends(get_db), user: User = Depends(require_viewer)):
    rows = db.scalars(select(Location).where(Location.organization_id == user.organization_id).order_by(Location.name))
    return [serialize_location(loc, db) for loc in rows]


@router.post("", status_code=201)
def create_location(body: LocationBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.scalar(select(Location.id).where(Location.organization_id == admin.organization_id, Location.name == body.name)):
        raise HTTPException(status_code=409, detail="A location with this name already exists.")
    hours = _hours(body.business_hours)
    loc = Location(
        organization_id=admin.organization_id, name=body.name, address=body.address, capacity=body.capacity,
        business_hours=json.dumps(hours) if hours is not None else None, is_active=body.is_active,
    )
    db.add(loc)
    db.flush()
    record_audit(db, admin, "location.create", "location", loc.id, {"name": loc.name})
    db.commit()
    return serialize_location(loc, db)


@router.patch("/{location_id}")
def update_location(location_id: int, body: LocationUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    loc = get_owned(db, Location, location_id, admin, "Location not found.")
    changes = {}
    if body.name is not None and body.name.strip() != loc.name:
        if db.scalar(select(Location.id).where(Location.organization_id == admin.organization_id, Location.name == body.name.strip(), Location.id != loc.id)):
            raise HTTPException(status_code=409, detail="A location with this name already exists.")
        changes["name"] = [loc.name, body.name.strip()]
        loc.name = body.name.strip()
    if body.address is not None and body.address.strip() != loc.address:
        changes["address"] = "changed"
        loc.address = body.address.strip()
    if body.clear_capacity:
        changes["capacity"] = [loc.capacity, None]
        loc.capacity = None
    elif body.capacity is not None and body.capacity != loc.capacity:
        changes["capacity"] = [loc.capacity, body.capacity]
        loc.capacity = body.capacity
    if body.clear_business_hours:
        changes["business_hours"] = "cleared"
        loc.business_hours = None
    elif body.business_hours is not None:
        loc.business_hours = json.dumps(_hours(body.business_hours))
        changes["business_hours"] = "changed"
    if body.is_active is not None and body.is_active != loc.is_active:
        if not body.is_active:
            active = db.scalar(select(func.count()).select_from(Location).where(
                Location.organization_id == admin.organization_id, Location.is_active.is_(True))) or 0
            if active <= 1:
                raise HTTPException(status_code=409, detail="At least one active location is required.")
        changes["is_active"] = [loc.is_active, body.is_active]
        loc.is_active = body.is_active
    if changes:
        loc.updated_at = utcnow()
        record_audit(db, admin, "location.update", "location", loc.id, changes)
    db.commit()
    from services.alert_engine import invalidate_rules

    invalidate_rules(admin.organization_id)
    return serialize_location(loc, db)
