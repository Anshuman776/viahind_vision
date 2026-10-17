"""
VIAHIND Vision management commands (run from backend/).

    python manage.py migrate
    python manage.py create-org <slug> "<name>" [--timezone Asia/Kolkata] [--plan standard] [--max-cameras N]
    python manage.py list-orgs
    python manage.py create-user <username> [--role admin|operator|viewer] [--org default]   (prompts for the password)
    python manage.py seed-demo                                                               (APP_ENV=demo only)
    python manage.py train-anomaly-model [--org default] [--days 60]
    python manage.py train-fight-model --data <dir> [--epochs 8] [--pretrained-backbone]
    python manage.py retention
"""

import argparse
import getpass
import random
import sys
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select


def _org_id(db, slug: str) -> int:
    from models.entities import Organization

    org_id = db.scalar(select(Organization.id).where(Organization.slug == slug))
    if org_id is None:
        raise SystemExit(f"Unknown organization '{slug}'. Run: python manage.py list-orgs")
    return org_id


def cmd_migrate(_args) -> int:
    from main import run_migrations

    run_migrations()
    print("Database is up to date.")
    return 0


def cmd_create_org(args) -> int:
    from db import session_scope
    from main import run_migrations
    from services.audit import record_audit
    from services.tenancy import create_organization

    run_migrations()
    with session_scope() as db:
        try:
            org = create_organization(db, args.name, args.slug, args.timezone, args.plan, args.max_cameras)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        record_audit(db, None, "organization.create", "organization", org.id, {"slug": org.slug, "plan": org.plan}, organization_id=org.id)
        print(f"Created organization '{org.name}' (slug {org.slug}, id {org.id}).")
    return 0


def cmd_list_orgs(_args) -> int:
    from db import session_scope
    from main import run_migrations
    from models.entities import Organization

    run_migrations()
    with session_scope() as db:
        for org in db.scalars(select(Organization).order_by(Organization.id)):
            print(f"{org.id:>4}  {org.slug:<24} {org.name}  [{org.plan}{', inactive' if not org.is_active else ''}]")
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
        org_id = _org_id(db, args.org)
        if db.scalar(select(User).where(func.lower(User.username) == args.username.lower())):
            print("That username already exists.", file=sys.stderr)
            return 1
        db.add(User(organization_id=org_id, username=args.username, password_hash=hash_password(password), role=args.role))
    print(f"Created {args.role} account '{args.username}' in organization '{args.org}'.")
    return 0


def cmd_seed_demo(args) -> int:
    """Synthetic records for demonstrations. Refuses to run outside APP_ENV=demo."""
    from config import settings
    from db import session_scope
    from main import run_migrations
    from models.entities import Camera, DetectionEvent, Location, Visit
    from services.site_settings import allocate_person_label, get_site_settings, site_zone

    if not settings.IS_DEMO:
        print("seed-demo only runs with APP_ENV=demo (it writes to DEMO_DATABASE_URL, never the real database).", file=sys.stderr)
        return 1
    run_migrations()
    rng = random.Random(args.seed)
    with session_scope() as db:
        org_id = _org_id(db, "default")
        if db.scalar(select(func.count()).select_from(DetectionEvent)):
            print("The demo database already has events; delete it to reseed.", file=sys.stderr)
            return 1
        row = get_site_settings(db, org_id)
        row.site_name = "Demo Store (synthetic data)"
        loc = db.scalar(select(Location).where(Location.organization_id == org_id).order_by(Location.id).limit(1))
        loc.name, loc.capacity = "Demo Store", 60
        loc.business_hours = '{"mon": [["09:00", "21:00"]], "tue": [["09:00", "21:00"]], "wed": [["09:00", "21:00"]], "thu": [["09:00", "21:00"]], "fri": [["09:00", "22:00"]], "sat": [["10:00", "22:00"]], "sun": [["10:00", "20:00"]]}'
        cam = db.get(Camera, "CAM-DEMO-ENTRANCE") or Camera(id="CAM-DEMO-ENTRANCE", organization_id=org_id, location_id=loc.id,
                                                            name="Demo Entrance", location="Synthetic", source_type="browser")
        db.add(cam)
        db.flush()
        tz = site_zone(row)
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(args.days - 1, -1, -1):
            start = today - timedelta(days=day_offset)
            for _ in range(rng.randint(25, 60)):
                entry_at = start + timedelta(hours=rng.triangular(9, 21, 18))
                if entry_at > datetime.now(tz):
                    continue
                label = allocate_person_label(db, org_id)
                entry = DetectionEvent(id=str(uuid.uuid4()), organization_id=org_id, location_id=loc.id, camera_id=cam.id,
                                       occurred_at=entry_at, event_type="entry", original_event_type="entry",
                                       person_label=label, confidence=round(rng.uniform(0.55, 0.92), 2), is_demo=True)
                db.add(entry)
                db.flush()
                visit = Visit(organization_id=org_id, location_id=loc.id, person_label=label, entry_event_id=entry.id,
                              entry_at=entry_at, entry_camera_id=cam.id, status="inside", match_method="tracker")
                db.add(visit)
                db.flush()
                entry.visit_id = visit.id
                exit_at = entry_at + timedelta(minutes=rng.uniform(5, 90))
                if exit_at < datetime.now(tz) and rng.random() < 0.95:
                    matched = rng.random() < 0.5
                    exit_label = label if matched else allocate_person_label(db, org_id)
                    exit_event = DetectionEvent(id=str(uuid.uuid4()), organization_id=org_id, location_id=loc.id, camera_id=cam.id,
                                                occurred_at=exit_at, event_type="exit", original_event_type="exit",
                                                person_label=exit_label, confidence=round(rng.uniform(0.55, 0.92), 2), is_demo=True,
                                                match_status="matched" if matched else "unmatched", visit_id=visit.id if matched else None)
                    db.add(exit_event)
                    if matched:
                        visit.exit_event_id, visit.exit_at, visit.exit_camera_id, visit.status = exit_event.id, exit_at, cam.id, "exited"
        print(f"Seeded {args.days} days of synthetic demo records (no snapshots: demo mode never shows fabricated photos). "
              "Demo events are excluded from ML training.")
    return 0


def cmd_train(args) -> int:
    from db import session_scope
    from main import run_migrations
    from services.ml_anomaly import train_model

    run_migrations()
    with session_scope() as db:
        org_id = _org_id(db, args.org)
    result = train_model(org_id, trained_by="cli", days=args.days)
    print(f"{result['status']}: {result['message']}")
    return 0 if result["status"] in ("ready", "insufficient_data") else 1


def cmd_train_fight(args) -> int:
    """Train the video altercation classifier from labelled clips (see vision/fight_model.py)."""
    from pathlib import Path

    from config import settings
    from vision import fight_model

    data = Path(args.data)
    if not data.is_dir():
        print(f"{data} is not a directory.", file=sys.stderr)
        return 1
    out = Path(settings.MODEL_DIR) / "video"
    try:
        result = fight_model.train(data, out, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
                                   pretrained_backbone=args.pretrained_backbone, device=args.device or settings.DETECTION_DEVICE,
                                   limit=args.limit, workers=args.workers)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    m = result["holdout_metrics"]
    print(f"Hold-out accuracy {m['accuracy']}, precision {m['precision']}, recall {m['recall']}, F1 {m['f1']} at threshold {m['threshold']}.")
    if args.activate:
        if m["f1"] < args.min_f1:
            print(f"Not activated: validation F1 {m['f1']} is below --min-f1 {args.min_f1}. The motion detector stays in use.", file=sys.stderr)
            return 2
        _set_env({"FIGHT_MODEL_PATH": result["weights"], "FIGHT_MODEL_SHA256": result["sha256"]})
        print("Activated in backend/.env (FIGHT_MODEL_PATH, FIGHT_MODEL_SHA256). Restart the backend to load it.")
        return 0
    print("To use it, set in backend/.env and restart:")
    print(f"  FIGHT_MODEL_PATH={result['weights']}")
    print(f"  FIGHT_MODEL_SHA256={result['sha256']}")
    return 0


def _set_env(values: dict) -> None:
    """Set or replace KEY=value lines in backend/.env (other lines are kept as they are)."""
    from config import ENV_FILE

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines[i] = f"{key}={values[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    ENV_FILE.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


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
    p = sub.add_parser("create-org")
    p.add_argument("slug")
    p.add_argument("name")
    p.add_argument("--timezone", default="Asia/Kolkata")
    p.add_argument("--plan", default="standard")
    p.add_argument("--max-cameras", type=int, default=None)
    p.set_defaults(func=cmd_create_org)
    sub.add_parser("list-orgs").set_defaults(func=cmd_list_orgs)
    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.add_argument("--role", choices=["admin", "operator", "viewer"], default="operator")
    p.add_argument("--org", default="default", help="organization slug (default: default)")
    p.set_defaults(func=cmd_create_user)
    p = sub.add_parser("seed-demo")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--days", type=int, default=14)
    p.set_defaults(func=cmd_seed_demo)
    p = sub.add_parser("train-anomaly-model")
    p.add_argument("--org", default="default")
    p.add_argument("--days", type=int, default=60)
    p.set_defaults(func=cmd_train)
    p = sub.add_parser("train-fight-model", help="train the video altercation classifier from labelled clips")
    p.add_argument("--data", required=True, help="folder with fight/ and nonfight/ (or violence/ and noviolence/) sub-folders of videos")
    p.add_argument("--epochs", type=int, default=15)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--limit", type=int, default=None, help="use only N training videos (quick trial)")
    p.add_argument("--device", default=None, help="cuda:0 or cpu (default: DETECTION_DEVICE)")
    p.add_argument("--workers", type=int, default=4, help="parallel video decoders")
    p.add_argument("--activate", action="store_true", help="write FIGHT_MODEL_PATH/SHA256 into backend/.env if the model passes --min-f1")
    p.add_argument("--min-f1", type=float, default=0.75, help="minimum validation F1 required to activate (default 0.75)")
    p.add_argument("--pretrained-backbone", action="store_true", help="download ImageNet MobileNetV3 weights to start from (recommended)")
    p.set_defaults(func=cmd_train_fight)
    sub.add_parser("retention").set_defaults(func=cmd_retention)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
