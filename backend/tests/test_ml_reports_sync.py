"""Isolation Forest baseline, reports/dashboard filters, hybrid sync and migrations.

SYNTHETIC TEST FIXTURES: the event histories generated here exist only to exercise the code paths.
They are never used to train a production model (production training reads real stored events).
"""

import json
import random
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import db
from models.entities import AnomalyModel, Camera, CameraIncident, DetectionEvent, Location, SyncNode, SyncOutbox
from services import ml_anomaly
from services.events import EventRecorder
from services.site_settings import get_site_settings, local_day_bounds
from tests.conftest import CSRF, login
from vision.line_crossing import CrossingEvent

sklearn_ok, _ = ml_anomaly.ml_available()
needs_sklearn = pytest.mark.skipif(not sklearn_ok, reason="scikit-learn not installed in this environment")


def _event(kind, at, camera="CAM-ENTRANCE-01", location=1, demo=False):
    return DetectionEvent(id=str(uuid.uuid4()), organization_id=1, location_id=location, camera_id=camera, occurred_at=at,
                          event_type=kind, original_event_type=kind, person_label="Unknown Person 01", is_demo=demo)


def _synthetic_history(days=10, seed=1, demo=False):
    """Synthetic fixture: a shop open 10:00-20:00 with a steady trickle of visitors."""
    rng = random.Random(seed)
    now = db.utcnow().replace(minute=0, second=0, microsecond=0)
    with db.session_scope() as s:
        for d in range(days, 0, -1):
            day = now - timedelta(days=d)
            for hour in range(24):
                n = rng.randint(3, 8) if 4 <= hour <= 14 else rng.randint(0, 1)  # UTC hours ~ IST 10:00-20:00
                for _ in range(n):
                    at = day.replace(hour=hour) + timedelta(minutes=rng.uniform(0, 59))
                    s.add(_event("entry", at, demo=demo))
                    s.add(_event("exit", at + timedelta(minutes=5), demo=demo))


# -- ML ----------------------------------------------------------------------------------------------

def test_insufficient_data_is_recorded_not_faked(camera):
    _synthetic_history(days=2)
    result = ml_anomaly.train_model(1, "test", days=30)
    assert result["status"] == "insufficient_data" and not result["has_artifact"]
    assert "need" in result["message"]


def test_demo_events_are_excluded_from_training(camera):
    _synthetic_history(days=10, demo=True)
    assert ml_anomaly.train_model(1, "test", days=30)["status"] == "insufficient_data"


@needs_sklearn
def test_train_score_and_explain(camera):
    _synthetic_history(days=10)
    result = ml_anomaly.train_model(1, "test", days=30)
    assert result["status"] == "ready" and result["active"] and result["has_artifact"]
    assert result["features"] == list(ml_anomaly.FEATURES)
    with db.session_scope() as s:
        model = s.scalar(select(AnomalyModel).where(AnomalyModel.active.is_(True)))
        estimator = ml_anomaly.load_artifact(model)
        tz = get_site_settings(s, 1).timezone
        from zoneinfo import ZoneInfo

        hour = datetime.now(ZoneInfo(tz)).replace(hour=3, minute=0, second=0, microsecond=0)
        unusual = {"hour_start": hour.astimezone(timezone.utc), "local_hour": 3, "entries": 80, "exits": 2, "uncertain": 0,
                   "net_flow": 78, **ml_anomaly.time_features(hour)}
        findings = ml_anomaly.score_rows(model, estimator, [unusual])
    assert len(findings) == 1
    assert "80 entries" in findings[0]["reason"] and "not evidence" in findings[0]["reason"]
    assert findings[0]["metrics"]["entries"] == 80


@needs_sklearn
def test_invalid_features_are_skipped(camera):
    _synthetic_history(days=10)
    ml_anomaly.train_model(1, "test", days=30)
    with db.session_scope() as s:
        model = s.scalar(select(AnomalyModel).where(AnomalyModel.active.is_(True)))
        estimator = ml_anomaly.load_artifact(model)
        bad = [{"hour_start": db.utcnow(), "local_hour": 1, "entries": None, "exits": 0, "uncertain": 0, "net_flow": 0,
                "hour_sin": 0, "hour_cos": 1, "dow_sin": 0, "dow_cos": 1},
               {"hour_start": db.utcnow(), "local_hour": 1, "entries": float("nan"), "exits": 0, "uncertain": 0, "net_flow": 0,
                "hour_sin": 0, "hour_cos": 1, "dow_sin": 0, "dow_cos": 1},
               {"hour_start": db.utcnow(), "local_hour": 1, "entries": -4, "exits": 0, "uncertain": 0, "net_flow": 0,
                "hour_sin": 0, "hour_cos": 1, "dow_sin": 0, "dow_cos": 1}]
        assert ml_anomaly.score_rows(model, estimator, bad) == []


@needs_sklearn
def test_tampered_artifact_is_refused(camera):
    _synthetic_history(days=10)
    ml_anomaly.train_model(1, "test", days=30)
    with db.session_scope() as s:
        model = s.scalar(select(AnomalyModel).where(AnomalyModel.active.is_(True)))
        path = ml_anomaly._model_root() / model.artifact_path
        path.write_bytes(path.read_bytes() + b"tamper")
    assert ml_anomaly.run_inference(1) == []
    with db.session_scope() as s:
        model = s.scalar(select(AnomalyModel).order_by(AnomalyModel.id.desc()))
        assert model.status == "failed" and not model.active and "integrity" in model.message


def test_hours_with_camera_outage_are_excluded(camera):
    _synthetic_history(days=1)
    now = db.utcnow()
    with db.session_scope() as s:
        s.add(CameraIncident(organization_id=1, camera_id=camera, kind="disconnected", message="x",
                             started_at=now - timedelta(days=3), ended_at=now))
        tz = get_site_settings(s, 1)
        from services.site_settings import site_zone

        rows = ml_anomaly.hourly_rows(s, 1, 1, now - timedelta(days=2), now, site_zone(tz))
    assert rows == []


def test_ml_status_api_admin_only(client, users):
    login(client, "operator", users["operator"])
    assert client.get("/api/v1/ml/anomaly-model").status_code == 403
    client.post("/api/v1/auth/logout", headers=CSRF)
    login(client, "admin", users["admin"])
    data = client.get("/api/v1/ml/anomaly-model").json()
    assert data["active"] is None and data["requirements"]["min_hours"] >= 1
    r = client.post("/api/v1/ml/anomaly-model/train", json={"days": 30}, headers=CSRF)
    assert r.status_code == 200 and r.json()["status"] in ("insufficient_data", "failed")


# -- reports and dashboard filters -------------------------------------------------------------------

@pytest.fixture
def two_cameras(camera):
    with db.session_scope() as s:
        s.add(Location(id=2, organization_id=1, name="Branch 2", address=""))
        s.flush()
        s.add(Camera(id="CAM-BRANCH", organization_id=1, location_id=2, name="Branch door", source_type="browser"))
    return camera, "CAM-BRANCH"


def test_period_report_totals_peaks_and_comparison(client, users, two_cameras):
    main_cam, branch_cam = two_cameras
    with db.session_scope() as s:
        row = get_site_settings(s, 1)
        today = datetime.now(timezone.utc).date()
        start, _ = local_day_bounds(row, today - timedelta(days=1))
        prev_start, _ = local_day_bounds(row, today - timedelta(days=2))
        for i in range(3):
            s.add(_event("entry", start + timedelta(hours=11, minutes=i)))
        s.add(_event("exit", start + timedelta(hours=12)))
        s.add(_event("entry", start + timedelta(hours=15), camera=branch_cam, location=2))
        s.add(_event("entry", prev_start + timedelta(hours=11)))
        rejected = _event("entry", start + timedelta(hours=13))
        rejected.review_status = "rejected"
        s.add(rejected)
    d = (today - timedelta(days=1)).isoformat()
    login(client, "viewer", users["viewer"])
    rep = client.get(f"/api/v1/reports/summary?date_from={d}&date_to={d}").json()
    assert rep["totals"]["entries"] == 4 and rep["totals"]["exits"] == 1  # rejected excluded
    assert rep["peak_hours"][0]["hour"] == 11 and rep["peak_hours"][0]["entries"] == 3
    assert rep["comparison"]["previous"]["entries"] == 1 and rep["comparison"]["entries_change_pct"] == 300.0
    assert {c["camera_name"]: c["entries"] for c in rep["cameras"]} == {"Main Entrance": 3, "Branch door": 1}
    loc_only = client.get(f"/api/v1/reports/summary?date_from={d}&date_to={d}&location_id=2").json()
    assert loc_only["totals"]["entries"] == 1
    cam_only = client.get(f"/api/v1/reports/summary?date_from={d}&date_to={d}&camera_id={main_cam}").json()
    assert cam_only["totals"]["entries"] == 3
    csv_text = client.get(f"/api/v1/reports/export.csv?date_from={d}&date_to={d}&section=cameras").text
    assert "Main Entrance,3" in csv_text
    assert client.get(f"/api/v1/reports/summary?date_from={d}&date_to=2000-01-01").status_code == 422


def test_overview_location_filter_and_per_location_occupancy(client, users, two_cameras):
    main_cam, branch_cam = two_cameras
    EventRecorder().record(main_cam, "s", CrossingEvent("entry", 1, time.time(), 0.9, (0, 0, 1, 1)), None)
    EventRecorder().record(branch_cam, "s", CrossingEvent("entry", 1, time.time(), 0.9, (0, 0, 1, 1)), None)
    EventRecorder().record(branch_cam, "s", CrossingEvent("entry", 2, time.time(), 0.9, (0, 0, 1, 1)), None)
    login(client, "operator", users["operator"])
    all_data = client.get("/api/v1/overview").json()
    assert all_data["occupancy"]["count"] == 3 and len(all_data["occupancy"]["locations"]) == 2
    branch = client.get("/api/v1/overview?location_id=2").json()
    assert branch["today"]["entries"] == 2 and branch["occupancy"]["count"] == 2
    cam = client.get(f"/api/v1/overview?camera_id={main_cam}").json()
    assert cam["today"]["entries"] == 1
    assert "freshness" in all_data and all_data["freshness"]["last_event_at"]
    # With two locations a correction must name its location.
    assert client.post("/api/v1/occupancy/reconcile", json={"count": 0, "reason": "Closing"}, headers=CSRF).status_code == 422
    r = client.post("/api/v1/occupancy/reconcile", json={"location_id": 2, "count": 0, "reason": "Closing"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["count"] == 0
    assert client.get("/api/v1/occupancy").json()["count"] == 1


def test_occupancy_trend(client, users, camera):
    EventRecorder().record(camera, "s", CrossingEvent("entry", 1, time.time(), 0.9, (0, 0, 1, 1)), None)
    login(client, "viewer", users["viewer"])
    trend = client.get("/api/v1/occupancy/trend?location_id=1").json()["hourly"]
    assert len(trend) == 24 and max(h["occupancy"] or 0 for h in trend) == 1


def test_locations_api_and_business_hours_validation(client, users):
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/locations", json={"name": "Mall Kiosk", "capacity": 10,
                                                "business_hours": {"mon": [["10:00", "22:00"]]}}, headers=CSRF)
    assert r.status_code == 201 and r.json()["business_hours"] == {"mon": [["10:00", "22:00"]]}
    bad = client.post("/api/v1/locations", json={"name": "Bad", "business_hours": {"mon": [["25:00", "22:00"]]}}, headers=CSRF)
    assert bad.status_code == 422
    loc_id = r.json()["id"]
    assert client.patch(f"/api/v1/locations/{loc_id}", json={"clear_capacity": True}, headers=CSRF).json()["capacity"] is None


# -- sync --------------------------------------------------------------------------------------------

def test_edge_outbox_is_written_with_events_and_corrections(camera, monkeypatch, users):
    from config import settings

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "edge")
    ev = EventRecorder().record(camera, "s", CrossingEvent("entry", 1, time.time(), 0.9, (0, 0, 1, 1)), b"\xff\xd8x")
    with db.session_scope() as s:
        rows = list(s.scalars(select(SyncOutbox)))
        assert len(rows) == 1 and rows[0].entity_id == ev["id"]
        payload = json.loads(rows[0].payload)
        assert "snapshot" not in json.dumps(payload) and "notes" not in payload


def test_push_once_retries_then_succeeds(camera, monkeypatch):
    from config import settings
    from services import sync

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "edge")
    ev = EventRecorder().record(camera, "s", CrossingEvent("entry", 1, time.time(), 0.9, (0, 0, 1, 1)), None)

    def offline(batch):
        raise ConnectionError("no internet")

    sent, err = sync.push_once(send=offline)
    assert sent == 0 and err
    with db.session_scope() as s:
        row = s.scalar(select(SyncOutbox))
        assert row.status == "pending" and row.attempts == 1
        row.next_attempt_at = db.utcnow()
    sent, err = sync.push_once(send=lambda batch: {"accepted": [b["id"] for b in batch]})
    assert sent == 1 and err is None
    with db.session_scope() as s:
        assert s.scalar(select(SyncOutbox)).status == "sent"


def test_cloud_ingest_is_idempotent_and_tenant_safe(client, users, monkeypatch):
    from config import settings
    from services.sync import hash_token
    from services.tenancy import create_organization

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "cloud")
    with db.session_scope() as s:
        s.add(SyncNode(id="edge-1", organization_id=1, location_id=1, name="Shop edge", token_hash=hash_token("tok-1")))
        other = create_organization(s, "Other", "other")
        loc2 = s.scalar(select(Location).where(Location.organization_id == other.id))
        s.add(SyncNode(id="edge-2", organization_id=other.id, location_id=loc2.id, name="Other edge", token_hash=hash_token("tok-2")))
    event_id = str(uuid.uuid4())
    item = {"id": event_id, "occurred_at": db.utcnow().isoformat(), "event_type": "entry", "person_label": "Unknown Person 01",
            "camera_name": "Front door", "review_status": "auto", "updated_at": db.utcnow().isoformat()}
    hdr = {"Authorization": "Bearer tok-1"}
    r1 = client.post("/api/v1/sync/events", json={"node_id": "edge-1", "events": [item]}, headers=hdr).json()
    r2 = client.post("/api/v1/sync/events", json={"node_id": "edge-1", "events": [item]}, headers=hdr).json()
    assert r1["accepted"] == [event_id] and r2["duplicates"] == [event_id]
    newer = {**item, "review_status": "rejected", "updated_at": (db.utcnow() + timedelta(seconds=5)).isoformat()}
    assert client.post("/api/v1/sync/events", json={"node_id": "edge-1", "events": [newer]}, headers=hdr).json()["accepted"] == [event_id]
    # Another tenant's node cannot overwrite this event.
    r = client.post("/api/v1/sync/events", json={"node_id": "edge-2", "events": [newer]}, headers={"Authorization": "Bearer tok-2"}).json()
    assert r["rejected"][0]["id"] == event_id
    assert client.post("/api/v1/sync/events", json={"node_id": "edge-1", "events": [item]}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    with db.session_scope() as s:
        rows = list(s.scalars(select(DetectionEvent)))
        assert len(rows) == 1 and rows[0].review_status == "rejected" and rows[0].organization_id == 1
        assert rows[0].source_camera_name == "Front door" and rows[0].camera_id is None
    login(client, "admin", users["admin"])
    assert client.get("/api/v1/events").json()["items"][0]["camera_name"] == "Front door"


def test_ingest_disabled_outside_cloud_mode(client):
    assert client.post("/api/v1/sync/events", json={"node_id": "x", "events": []}).status_code == 404


# -- migrations ---------------------------------------------------------------------------------------

def test_migrations_downgrade_and_upgrade(fresh_database):
    from alembic import command
    from alembic.config import Config

    from config import BASE_DIR

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    with db.session_scope() as s:
        assert s.get(Location, 1) is not None
