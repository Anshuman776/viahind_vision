"""Camera interruptions: periods in which entry/exit events may have been missed."""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from db import session_scope, utcnow
from models.entities import CameraIncident

logger = logging.getLogger("viahind.incidents")


def open_incident(camera_id: Optional[str], kind: str, message: str) -> None:
    """Record the start of an interruption unless one is already open for this camera."""
    try:
        with session_scope() as db:
            existing = db.scalar(
                select(CameraIncident).where(CameraIncident.camera_id == camera_id, CameraIncident.ended_at.is_(None))
            )
            if existing is None:
                db.add(CameraIncident(camera_id=camera_id, kind=kind, message=message[:500], started_at=utcnow()))
    except SQLAlchemyError:
        logger.exception("Could not record camera incident")


def close_incidents(camera_id: str) -> None:
    try:
        with session_scope() as db:
            for incident in db.scalars(
                select(CameraIncident).where(CameraIncident.camera_id == camera_id, CameraIncident.ended_at.is_(None))
            ):
                incident.ended_at = utcnow()
    except SQLAlchemyError:
        logger.exception("Could not close camera incidents")
