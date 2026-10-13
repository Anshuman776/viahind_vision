"""HTTP API: authentication, authorization, snapshot access, validation, filters and export."""

import time
import uuid

import pytest
from sqlalchemy import select

import db
from models.entities import Camera, DetectionEvent
from services.events import EventRecorder
from tests.conftest import CSRF, login
from vision.line_crossing import CrossingEvent


def record(camera, kind, track, jpeg=None, t=None):
    return EventRecorder().record(camera, "s1", CrossingEvent(kind, track, t or time.time(), 0.8, (0, 0, 10, 20)), jpeg)


def test_endpoints_require_sign_in(client):
    for path in ("/api/v1/overview", "/api/v1/events", "/api/v1/cameras", "/api/v1/occupancy", "/api/v1/users"):
        assert client.get(path).status_code == 401, path


def test_bad_credentials_and_throttling(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"username": "operator", "password": "wrong"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"username": "operator", "password": "OperatorPass123"})
    assert r.status_code == 429


def test_session_cookie_is_http_only(client, users):
    r = login(client, "operator", users["operator"])
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/v1/auth/me").json()["role"] == "operator"


def test_mutations_require_csrf_header(client, users, camera):
    login(client, "operator", users["operator"])
    body = {"count": 2, "reason": "Head count"}
    assert client.post("/api/v1/occupancy/reconcile", json=body).status_code == 403
    assert client.post("/api/v1/occupancy/reconcile", json=body, headers=CSRF).status_code == 200


def test_operator_cannot_use_admin_endpoints(client, users):
    login(client, "operator", users["operator"])
    assert client.get("/api/v1/users").status_code == 403
    assert client.put("/api/v1/settings", json={"site_name": "x"}, headers=CSRF).status_code == 403
    assert client.post("/api/v1/cameras", json={"id": "CAM-X", "name": "X", "source_type": "browser"}, headers=CSRF).status_code == 403


def test_camera_source_is_never_returned(client, users):
    login(client, "admin", users["admin"])
    body = {"id": "cam-gate-02", "name": "Gate", "source_type": "network", "source": "rtsp://guard:S3cret!@192.168.1.20:554/stream1"}
    r = client.post("/api/v1/cameras", json=body, headers=CSRF)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["id"] == "CAM-GATE-02"
    assert "S3cret" not in r.text and "guard" not in r.text
    assert data["source_description"] == "rtsp://***@192.168.1.20:554/stream1"
    listing = client.get("/api/v1/cameras").text
    assert "S3cret" not in listing
    with db.session_scope() as s:
        assert "S3cret" not in s.get(Camera, "CAM-GATE-02").source_secret  # encrypted at rest


@pytest.mark.parametrize(
    "source_type,source",
    [("network", "ftp://host/x"), ("network", "file:///etc/passwd"), ("device", "abc"), ("file", "../../secret.mp4"), ("network", "")],
)
def test_invalid_camera_sources_are_rejected(client, users, source_type, source):
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/cameras", json={"id": "CAM-BAD", "name": "Bad", "source_type": source_type, "source": source}, headers=CSRF)
    assert r.status_code == 422


def test_start_camera_without_frames_is_not_live(client, users, camera):
    login(client, "operator", users["operator"])
    r = client.post(f"/api/v1/cameras/{camera}/start", headers=CSRF)
    assert r.status_code == 200
    assert r.json()["runtime"]["status"] == "connecting"
    assert client.get(f"/api/v1/cameras/{camera}/frame").status_code == 404
    assert client.post(f"/api/v1/cameras/{camera}/stop", headers=CSRF).json()["runtime"]["status"] == "stopped"


def test_line_validation_and_update(client, users, camera):
    login(client, "operator", users["operator"])
    assert client.put(f"/api/v1/cameras/{camera}/line", json={"x1": 0.5, "y1": 0.5, "x2": 0.51, "y2": 0.5}, headers=CSRF).status_code == 422
    assert client.put(f"/api/v1/cameras/{camera}/line", json={"x1": 0.1, "y1": 0.5, "x2": 1.5, "y2": 0.5}, headers=CSRF).status_code == 422
    r = client.put(f"/api/v1/cameras/{camera}/line", json={"x1": 0.1, "y1": 0.5, "x2": 0.9, "y2": 0.5, "entry_side": -1}, headers=CSRF)
    assert r.status_code == 200 and r.json()["line"]["entry_side"] == -1


def test_snapshot_requires_auth_and_is_served(client, users, camera, snapshot_dir):
    payload = record(camera, "entry", 1, b"\xff\xd8\xff\xe0fake-jpeg")
    url = f"/api/v1/events/{payload['id']}/snapshot"
    assert client.get(url).status_code == 401
    login(client, "operator", users["operator"])
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "no-store" in r.headers["cache-control"]


def test_snapshot_path_cannot_escape_storage(client, users, camera, snapshot_dir):
    event_id = str(uuid.uuid4())
    with db.session_scope() as s:
        s.add(DetectionEvent(id=event_id, camera_id=camera, occurred_at=db.utcnow(), event_type="entry", original_event_type="entry",
                             person_label="Unknown Person 99", snapshot_path="../../conftest.py", snapshot_status="saved"))
    login(client, "operator", users["operator"])
    assert client.get(f"/api/v1/events/{event_id}/snapshot").status_code == 404


def test_overview_counts_come_from_events(client, users, camera, snapshot_dir):
    record(camera, "entry", 1)
    record(camera, "entry", 2)
    record(camera, "exit", 1)
    record(camera, "uncertain", 3)
    login(client, "operator", users["operator"])
    data = client.get("/api/v1/overview").json()
    assert data["occupancy"]["count"] == 1
    assert data["today"]["entries"] == 2 and data["today"]["exits"] == 1
    assert data["today"]["unknown_visitors"] == 2
    assert sum(h["entries"] for h in data["today"]["hourly"]) == 2
    assert len(data["recent_events"]) == 4


def test_event_filters_pagination_and_review(client, users, camera, snapshot_dir):
    for i in range(30):
        record(camera, "entry" if i % 2 else "exit", 100 + i)
    login(client, "operator", users["operator"])
    page = client.get("/api/v1/events", params={"event_type": "entry", "page_size": 10, "page": 2}).json()
    assert page["total"] == 15 and len(page["items"]) == 5
    found = client.get("/api/v1/events", params={"q": "Person 03"}).json()
    assert [e["person_label"] for e in found["items"]] == ["Unknown Person 03"]

    event_id = page["items"][0]["id"]
    r = client.patch(f"/api/v1/events/{event_id}", json={"review_status": "rejected", "notes": "Reflection in glass door"}, headers=CSRF)
    assert r.status_code == 200
    detail = r.json()
    assert detail["review_status"] == "rejected"
    assert detail["audit"][0]["action"] == "event.update" and detail["audit"][0]["username"] == "operator"
    assert client.get("/api/v1/events", params={"review_status": "rejected"}).json()["total"] == 1


def test_csv_export_is_audited_and_injection_safe(client, users, camera, snapshot_dir):
    payload = record(camera, "entry", 1)
    login(client, "operator", users["operator"])
    client.patch(f"/api/v1/events/{payload['id']}", json={"notes": "=HYPERLINK(\"http://evil\")"}, headers=CSRF)
    r = client.get("/api/v1/events/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("event_id,date,time")
    assert "'=HYPERLINK" in lines[1]
    login(client, "admin", users["admin"])
    assert any(a["action"] == "events.export" for a in client.get("/api/v1/audit").json())


def test_settings_validation(client, users):
    login(client, "admin", users["admin"])
    assert client.put("/api/v1/settings", json={"timezone": "Mars/Olympus"}, headers=CSRF).status_code == 422
    assert client.put("/api/v1/settings", json={"min_confidence": 2}, headers=CSRF).status_code == 422
    r = client.put("/api/v1/settings", json={"timezone": "Asia/Kolkata", "cooldown_seconds": 4}, headers=CSRF)
    assert r.status_code == 200 and r.json()["cooldown_seconds"] == 4


def test_last_admin_cannot_be_demoted(client, users):
    login(client, "admin", users["admin"])
    admin_id = next(u["id"] for u in client.get("/api/v1/users").json() if u["username"] == "admin")
    assert client.patch(f"/api/v1/users/{admin_id}", json={"role": "operator"}, headers=CSRF).status_code == 409


def test_weak_passwords_rejected(client, users):
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/users", json={"username": "guard2", "password": "alllowercase1"}, headers=CSRF)
    assert r.status_code == 422


def test_readiness_reports_database_and_detector(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["person_detector"]["ok"] is False  # no weights configured in tests


def ws_headers(client, origin="http://localhost:3000"):
    headers = {"origin": origin}
    token = client.cookies.get("vv_session")
    if token:
        headers["cookie"] = f"vv_session={token}"
    return headers


def test_websocket_requires_session_and_same_site_origin(client, users, camera):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://localhost/ws/alerts", headers=ws_headers(client)) as ws:
            ws.receive_text()
    login(client, "operator", users["operator"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://localhost/ws/alerts", headers=ws_headers(client, "https://evil.example")) as ws:
            ws.receive_text()
    with client.websocket_connect("ws://localhost/ws/alerts", headers=ws_headers(client)) as ws:
        ws.send_text("ping")  # accepted: signed in and same-site origin


def test_stream_requires_started_browser_camera(client, users, camera):
    from starlette.websockets import WebSocketDisconnect

    login(client, "operator", users["operator"])
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"ws://localhost/ws/stream/{camera}", headers=ws_headers(client)) as ws:
            ws.receive_text()
    assert exc.value.code == 4404


def test_browser_frames_flow_through_websocket(client, users, camera):
    import cv2
    import numpy as np

    login(client, "operator", users["operator"])
    client.post(f"/api/v1/cameras/{camera}/start", headers=CSRF)
    ok, jpeg = cv2.imencode(".jpg", np.full((120, 160, 3), 128, np.uint8))
    with client.websocket_connect(f"ws://localhost/ws/stream/{camera}", headers=ws_headers(client)) as ws:
        ws.send_bytes(jpeg.tobytes())
        deadline = time.time() + 3
        while time.time() < deadline and client.get(f"/api/v1/cameras/{camera}").json()["runtime"]["status"] != "live":
            time.sleep(0.05)
    cam = client.get(f"/api/v1/cameras/{camera}").json()
    assert cam["runtime"]["status"] == "live" and cam["runtime"]["last_frame_at"] is not None
    assert client.get(f"/api/v1/cameras/{camera}/frame").headers["content-type"] == "image/jpeg"
    client.post(f"/api/v1/cameras/{camera}/stop", headers=CSRF)


def test_database_outage_returns_503_on_readiness(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    import main

    class Broken:
        def __enter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(main, "SessionLocal", lambda: Broken())
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"]["ok"] is False
