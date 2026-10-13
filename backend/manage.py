"""
VIAHIND Vision management commands (run from backend/).

    python manage.py migrate
    python manage.py create-user <username> [--role admin|operator]     (prompts for the password)
    python manage.py seed-demo                                           (APP_ENV=demo only)
    python manage.py retention
"""

import argparse
import getpass
import random
import sys
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select


def cmd_migrate(_args) -> int:
    from main import run_migrations

    run_migrations()
    print("Database is up to date.")
    return 0


def cmd_create_user(args) -> int:
    from fastapi import HTTPException

    from auth import hash_password, validate_new_password
    from db import session_scope
    from main import run_migrations
    from models.entities import User

    run_migrations()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        validate_new_password(password)
    except HTTPException as exc:
        print(exc.detail, file=sys.stderr)
        return 1
    with session_scope() as db:
        if db.scalar(select(User).where(func.lower(User.username) == args.username.lower())):
            print("That username already exists.", file=sys.stderr)
            return 1
        db.add(User(username=args.username, password_hash=hash_password(password), role=args.role))
    print(f"Created {args.role} account '{args.username}'.")
    return 0


def cmd_seed_demo(args) -> int:
    """Synthetic records for demonstrations. Refuses to run outside APP_ENV=demo."""
    from config import settings
    from db import session_scope
    from main import run_migrations
    from models.entities import Camera, DetectionEvent, Visit
    from services.site_settings import allocate_person_label, get_site_settings, site_zone

    if not settings.IS_DEMO:
        print("seed-demo only runs with APP_ENV=demo (it writes to DEMO_DATABASE_URL, never the real database).", file=sys.stderr)
        return 1
    run_migrations()
    rng = random.Random(args.seed)
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(DetectionEvent)):
            print("The demo database already has events; delete it to reseed.", file=sys.stderr)
            return 1
        row = get_site_settings(db)
        row.site_name = "Demo PG (synthetic data)"
        cam = db.get(Camera, "CAM-DEMO-ENTRANCE") or Camera(id="CAM-DEMO-ENTRANCE", name="Demo Entrance", location="Synthetic", source_type="browser")
        db.add(cam)
        db.flush()
        tz = site_zone(row)
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in (1, 0):
            start = today - timedelta(days=day_offset)
            for _ in range(rng.randint(8, 14)):
                entry_at = start + timedelta(hours=rng.uniform(6, 21))
                if entry_at > datetime.now(tz):
                    continue
                label = allocate_person_label(db)
                entry = DetectionEvent(id=str(uuid.uuid4()), camera_id=cam.id, occurred_at=entry_at, event_type="entry", original_event_type="entry",
                                       person_label=label, confidence=round(rng.uniform(0.55, 0.92), 2), is_demo=True)
                db.add(entry)
                db.flush()
                visit = Visit(person_label=label, entry_event_id=entry.id, entry_at=entry_at, entry_camera_id=cam.id, status="inside", match_method="tracker")
                db.add(visit)
                db.flush()
                entry.visit_id = visit.id
                exit_at = entry_at + timedelta(minutes=rng.uniform(5, 240))
                if exit_at < datetime.now(tz) and rng.random() < 0.8:
                    matched = rng.random() < 0.5
                    exit_label = label if matched else allocate_person_label(db)
                    exit_event = DetectionEvent(id=str(uuid.uuid4()), camera_id=cam.id, occurred_at=exit_at, event_type="exit", original_event_type="exit",
                                                person_label=exit_label, confidence=round(rng.uniform(0.55, 0.92), 2), is_demo=True,
                                                match_status="matched" if matched else "unmatched", visit_id=visit.id if matched else None)
                    db.add(exit_event)
                    if matched:
                        visit.exit_event_id, visit.exit_at, visit.exit_camera_id, visit.status = exit_event.id, exit_at, cam.id, "exited"
        print("Seeded synthetic demo records (no snapshots: demo mode never shows fabricated photos).")
    return 0


def cmd_retention(_args) -> int:
    from main import run_migrations
    from services.retention import run_retention

    run_migrations()
    print(run_retention())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VIAHIND Vision management")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.add_argument("--role", choices=["admin", "operator"], default="operator")
    p.set_defaults(func=cmd_create_user)
    p = sub.add_parser("seed-demo")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_seed_demo)
    sub.add_parser("retention").set_defaults(func=cmd_retention)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
