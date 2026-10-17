"""Tenant isolation, role restrictions, session invalidation, SSRF policy and credential hygiene.

All data here is synthetic test fixture data.
"""

import logging
import time

import pytest
from sqlalchemy import select

import db
from auth import hash_password
from models.entities import Alert, Camera, CameraZone, DetectionEvent, Location, User
from services.events import EventRecorder
from services.tenancy import create_organization
from tests.conftest import CSRF, login
from vision.line_crossing import CrossingEvent

OTHER_PASSWORD = "OtherAdmin123"


@pytest.fixture
def other_org(users):
    """Tenant B with its own admin, location, camera, event and alert."""
    with db.session_scope() as s:
        org = create_organization(s, "Other Shop", "other-shop")
        loc = s.scalar(select(Location).where(Location.organization_id == org.id))
        s.add(User(organization_id=org.id, username="other-admin", password_hash=hash_password(OTHER_PASSWORD), role="admin"))
        s.add(Camera(id="CAM-B-1", organization_id=org.id, location_id=loc.id, name="B door", source_type="browser"))
        s.flush()
        org_id, loc_id = org.id, loc.id
    event = EventRecorder().record("CAM-B-1", "s1", CrossingEvent("entry", 1, time.time(), 0.9, (0, 0, 10, 20)), b"\xff\xd8jpeg")
    with db.session_scope() as s:
        s.add(Alert(id="00000000-0000-0000-0000-00000000000b", organization_id=org_id, location_id=loc_id, camera_id="CAM-B-1",
                    rule_type="after_hours", category="operations", severity="medium", title="B alert", reason="r", metrics="{}",
                    status="new", dedup_key="k", occurrences=1, first_seen_at=db.utcnow(), last_seen_at=db.utcnow(),
                    snapshot_status="none"))
        s.add(CameraZone(organization_id=org_id, camera_id="CAM-B-1", name="Stock room", kind="restricted",
                         polygon="[[0,0],[1,0],[1,1]]"))
    return {"org_id": org_id, "location_id": loc_id, "event_id": event["id"]}


def test_tenant_a_cannot_read_or_change_tenant_b(client, users, camera, other_org, snapshot_dir):
    login(client, "admin", users["admin"])
    ev = other_org["event_id"]
    # Lists never include the other tenant's rows.
    assert all(c["id"] != "CAM-B-1" for c in client.get("/api/v1/cameras").json())
    assert client.get("/api/v1/events").json()["total"] == 0
    assert client.get("/api/v1/alerts").json()["total"] == 0
    assert all(loc["id"] != other_org["location_id"] for loc in client.get("/api/v1/locations").json())
    assert all(u["username"] != "other-admin" for u in client.get("/api/v1/users").json())
    # Direct access behaves like a missing record.
    for path in (f"/api/v1/events/{ev}", f"/api/v1/events/{ev}/snapshot", "/api/v1/cameras/CAM-B-1",
                 "/api/v1/alerts/00000000-0000-0000-0000-00000000000b"):
        assert client.get(path).status_code == 404, path
    assert client.patch(f"/api/v1/events/{ev}", json={"review_status": "rejected"}, headers=CSRF).status_code == 404
    assert client.post("/api/v1/cameras/CAM-B-1/start", headers=CSRF).status_code == 404
    assert client.put("/api/v1/cameras/CAM-B-1/line", json={"x1": 0.1, "y1": 0.5, "x2": 0.9, "y2": 0.5}, headers=CSRF).status_code == 404
    assert client.post("/api/v1/alerts/00000000-0000-0000-0000-00000000000b/actions", json={"action": "dismiss"}, headers=CSRF).status_code == 404
    assert client.get(f"/api/v1/overview?location_id={other_org['location_id']}").status_code == 404
    assert client.get(f"/api/v1/reports/summary?date_from=2026-01-01&date_to=2026-01-02&location_id={other_org['location_id']}").status_code == 404
    other_user = None
    with db.session_scope() as s:
        other_user = s.scalar(select(User.id).where(User.username == "other-admin"))
    assert client.patch(f"/api/v1/users/{other_user}", json={"is_active": False}, headers=CSRF).status_code == 404
    with db.session_scope() as s:
        assert s.get(DetectionEvent, ev).review_status == "auto"
        assert s.get(User, other_user).is_active


def test_tenant_occupancy_and_overview_are_separate(client, users, camera, other_org):
    login(client, "other-admin", OTHER_PASSWORD)
    data = client.get("/api/v1/overview").json()
    assert data["today"]["entries"] == 1 and data["occupancy"]["count"] == 1
    client.post("/api/v1/auth/logout", headers=CSRF)
    login(client, "admin", users["admin"])
    data = client.get("/api/v1/overview").json()
    assert data["today"]["entries"] == 0 and data["occupancy"]["count"] == 0


def test_camera_id_taken_by_other_tenant_does_not_leak_details(client, users, other_org):
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/cameras", json={"id": "CAM-B-1", "name": "x", "source_type": "browser"}, headers=CSRF)
    assert r.status_code == 409 and "B door" not in r.text


def test_websocket_broadcasts_are_organization_scoped():
    import asyncio

    from websocket import AlertConnectionManager

    sent = {"a": [], "b": []}

    class FakeSocket:
        def __init__(self, key):
            self.key = key

        async def accept(self):
            pass

        async def send_json(self, message):
            sent[self.key].append(message)

    async def run():
        mgr = AlertConnectionManager()
        await mgr.connect_alerts(FakeSocket("a"), 1)
        await mgr.connect_alerts(FakeSocket("b"), 2)
        await mgr.broadcast_alert({"type": "event_recorded"}, 1)

    asyncio.run(run())
    assert len(sent["a"]) == 1 and sent["b"] == []


def test_viewer_role_is_read_only(client, users, camera):
    login(client, "viewer", users["viewer"])
    assert client.get("/api/v1/overview").status_code == 200
    assert client.get("/api/v1/reports/summary?date_from=2026-10-01&date_to=2026-10-02").status_code == 200
    assert client.get("/api/v1/overview").json()["recent_events"] == []
    for method, path in (("get", "/api/v1/events"), ("get", "/api/v1/alerts"), ("post", f"/api/v1/cameras/{camera}/start"),
                         ("post", "/api/v1/occupancy/reconcile")):
        r = getattr(client, method)(path, headers=CSRF, **({"json": {"count": 1, "reason": "xyz"}} if method == "post" else {}))
        assert r.status_code == 403, path
    cams = client.get("/api/v1/cameras").json()
    assert cams and cams[0]["source_description"] is None


def test_password_reset_and_role_change_end_sessions(client, users):
    login(client, "operator", users["operator"])
    assert client.get("/api/v1/auth/me").status_code == 200
    with db.session_scope() as s:
        s.scalar(select(User).where(User.username == "operator")).role = "viewer"
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "operator", users["operator"])
    with db.session_scope() as s:
        s.scalar(select(User).where(User.username == "operator")).password_hash = hash_password("NewPassword123")
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("url", [
    "rtsp://169.254.169.254/latest/meta-data",  # cloud metadata (link-local)
    "http://127.0.0.1:8000/api/v1/users",  # loopback: the API itself
    "rtsp://[::1]/stream",
    "rtsp://8.8.8.8/stream",  # public address outside CAMERA_ALLOWED_NETWORKS
    "rtsp://0.0.0.0/stream",
    "rtsp://224.0.0.1/stream",
])
def test_camera_urls_are_restricted_to_camera_networks(client, users, url):
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/cameras", json={"id": "CAM-SSRF", "name": "x", "source_type": "network", "source": url}, headers=CSRF)
    assert r.status_code == 422, url
    assert "not allowed" in r.json()["detail"]


def test_private_camera_url_allowed_and_rechecked_at_start(monkeypatch):
    from config import settings
    from vision.sources import SourceError, resolve_source, validate_source

    assert validate_source("network", "rtsp://user:pw@192.168.1.64:554/Streaming/Channels/101")
    monkeypatch.setattr(settings, "CAMERA_ALLOWED_NETWORKS", "10.0.0.0/8")
    with pytest.raises(SourceError):
        resolve_source("network", "rtsp://user:pw@192.168.1.64:554/x")


def test_camera_credentials_never_logged_or_returned(client, users, caplog):
    caplog.set_level(logging.DEBUG)
    login(client, "admin", users["admin"])
    secret_url = "rtsp://guard:Sup3rSecretPW@192.168.1.30:554/stream1"
    r = client.post("/api/v1/cameras", json={"id": "CAM-CRED", "name": "Cred", "source_type": "network", "source": secret_url}, headers=CSRF)
    assert r.status_code == 201
    r = client.post("/api/v1/cameras/test-source", json={"source_type": "network", "source": "rtsp://guard:Sup3rSecretPW@10.255.255.1:554/x"}, headers=CSRF)
    assert "Sup3rSecretPW" not in r.text
    for path in ("/api/v1/cameras", "/api/v1/cameras/CAM-CRED", "/api/v1/audit", "/api/v1/settings"):
        assert "Sup3rSecretPW" not in client.get(path).text, path
    assert "Sup3rSecretPW" not in caplog.text


def test_rate_limiter_blocks_bursts():
    from main import RateLimiter

    limiter = RateLimiter(per_minute=5)
    assert all(limiter.allow("1.2.3.4") for _ in range(5))
    assert not limiter.allow("1.2.3.4")
    assert limiter.allow("5.6.7.8")
    assert not RateLimiter(per_minute=5).allow("x", cost=10)


def test_plan_camera_limit(client, users):
    from models.entities import Organization

    with db.session_scope() as s:
        s.get(Organization, 1).max_cameras = 1
    login(client, "admin", users["admin"])
    assert client.post("/api/v1/cameras", json={"id": "CAM-1", "name": "a", "source_type": "browser"}, headers=CSRF).status_code == 201
    assert client.post("/api/v1/cameras", json={"id": "CAM-2", "name": "b", "source_type": "browser"}, headers=CSRF).status_code == 402


def test_admin_can_delete_snapshot_with_audit(client, users, camera, snapshot_dir):
    event = EventRecorder().record(camera, "s1", CrossingEvent("entry", 5, time.time(), 0.9, (0, 0, 10, 20)), b"\xff\xd8jpeg")
    login(client, "operator", users["operator"])
    assert client.delete(f"/api/v1/events/{event['id']}/snapshot", headers=CSRF).status_code == 403
    client.post("/api/v1/auth/logout", headers=CSRF)
    login(client, "admin", users["admin"])
    assert client.get(f"/api/v1/events/{event['id']}/snapshot").status_code == 200
    assert client.delete(f"/api/v1/events/{event['id']}/snapshot", headers=CSRF).status_code == 204
    assert client.get(f"/api/v1/events/{event['id']}/snapshot").status_code == 404
    assert client.get(f"/api/v1/events/{event['id']}").json()["snapshot_status"] == "deleted"
    assert any(a["action"] == "event.snapshot_delete" for a in client.get("/api/v1/audit").json())


def test_unauthenticated_network_info_route_removed():
    from pathlib import Path

    assert not (Path(__file__).resolve().parents[2] / "frontend" / "app" / "api" / "network-info").exists()
