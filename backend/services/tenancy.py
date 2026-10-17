"""
Tenant isolation helpers.

Every API handler that reads or writes business data goes through these helpers, so a record
belonging to another organization behaves exactly like a record that does not exist (404),
and list queries never return another organization's rows.
"""

import re
from typing import Optional, Type, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import utcnow
from models.entities import Camera, Location, Organization, SiteSettings, User

T = TypeVar("T")

SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}$")


def get_owned(db: Session, model: Type[T], key, user: User, not_found: str = "Not found.") -> T:
    """Load a row by primary key and return 404 unless it belongs to the user's organization."""
    row = db.get(model, key)
    if row is None or getattr(row, "organization_id", None) != user.organization_id:
        raise HTTPException(status_code=404, detail=not_found)
    return row


def owned_location(db: Session, user: User, location_id: Optional[int]) -> Optional[Location]:
    if location_id is None:
        return None
    return get_owned(db, Location, location_id, user, "Location not found.")


def owned_camera(db: Session, user: User, camera_id: Optional[str]) -> Optional[Camera]:
    if not camera_id:
        return None
    return get_owned(db, Camera, camera_id, user, "Camera not found.")


def default_location(db: Session, organization_id: int) -> Location:
    loc = db.scalar(select(Location).where(Location.organization_id == organization_id).order_by(Location.id).limit(1))
    if loc is None:
        loc = Location(organization_id=organization_id, name="Main location", address="")
        db.add(loc)
        db.flush()
    return loc


def create_organization(db: Session, name: str, slug: str, timezone: str = "Asia/Kolkata",
                        plan: str = "standard", max_cameras: Optional[int] = None) -> Organization:
    """Create a tenant with its settings row and a first location. Caller commits."""
    slug = slug.strip().lower()
    if not SLUG.match(slug):
        raise ValueError("Organization slugs use 2-63 lower-case letters, digits and hyphens.")
    if db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        raise ValueError("An organization with this slug already exists.")
    org = Organization(name=name.strip(), slug=slug, plan=plan, max_cameras=max_cameras)
    db.add(org)
    db.flush()
    db.add(SiteSettings(organization_id=org.id, site_name=org.name, timezone=timezone, updated_at=utcnow()))
    default_location(db, org.id)
    db.flush()
    return org
