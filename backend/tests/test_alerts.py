"""Zone monitoring, alert rules, deduplication/cooldown, review workflow and notifications.
All trajectories, frames and events are synthetic test fixtures."""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import db
from models.entities import Alert, CameraIncident, Location, NotificationChannel, NotificationDelivery
from services import alert_engine, notifications
from services.alert_rules import save_rule, validate_params
from services.alerts import AlertDraft, raise_alert
from services.business_hours import is_open, validate_hours
from services.events import EventRecorder
from tests.conftest import CSRF, login
from vision.camera_worker import CameraSpec
from vision.line_crossing import CrossingEvent, Detection
from vision.zones import ZoneConfig, ZoneMonitor, point_in_polygon

SQUARE = ((0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6))


def det(track, cx, cy, w=640, h=480, conf=0.9):
    # Box whose bottom-centre anchor sits at (cx, cy) in normalised coordinates.
    x, y = cx * w, cy * h
    return Detection(track, (x - 20, y - 80, x + 20, y), conf)


@pytest.fixture(autouse=True)
def fresh_rule_cache():
    alert_engine._rule_cache.clear()
    yield


# -- zone monitor ----------------------------------------------------------------------------------

def test_point_in_polygon():
    assert point_in_polygon(0.4, 0.4, SQUARE)
    assert not point_in_polygon(0.7, 0.4, SQUARE)


def test_restricted_zone_needs_confirmed_presence_and_fires_once():
    mon = ZoneMonitor([ZoneConfig(1, "Stock room", "restricted", SQUARE)], min_frames=3)
    events = []
    for i in range(10):
        events += mon.update([det(7, 0.4, 0.4)], 100 + i * 0.2, (640, 480))
    assert [e.kind for e in events] == ["zone_entered"]
    assert events[0].track_id == 7


def test_single_noisy_frame_in_zone_is_ignored():
    mon = ZoneMonitor([ZoneConfig(1, "Stock room", "restricted", SQUARE)], min_frames=3)
    events = mon.update([det(7, 0.4, 0.4)], 100, (640, 480))
    for i in range(5):
        events += mon.update([det(7, 0.8, 0.8)], 101 + i, (640, 480))
    assert events == []


def test_dwell_threshold_and_brief_occlusion():
    mon = ZoneMonitor([ZoneConfig(2, "Counter", "monitored", SQUARE, dwell_seconds=30)], min_frames=2, exit_grace_seconds=3)
    events = []
    t = 0.0
    while t < 20:
        events += mon.update([det(3, 0.4, 0.4)], t, (640, 480))
        t += 1
    events += mon.update([], 21, (640, 480))  # occluded for 2 s: still the same stay
    t = 23.0
    while t < 40:
        events += mon.update([det(3, 0.4, 0.4)], t, (640, 480))
        t += 1
    assert [e.kind for e in events] == ["dwell_exceeded"]
    assert events[0].dwell_seconds >= 30
    assert mon.occupancy() == {2: 1}


def test_low_confidence_and_untracked_detections_ignored():
    mon = ZoneMonitor([ZoneConfig(1, "Z", "restricted", SQUARE)], min_frames=1, min_confidence=0.5)
    assert mon.update([det(None, 0.4, 0.4), det(4, 0.4, 0.4, conf=0.2)], 1, (640, 480)) == []


# -- business hours ----------------------------------------------------------------------------------

def test_business_hours_including_past_midnight():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    hours = validate_hours({"fri": [["18:00", "02:00"]], "mon": [["09:00", "21:00"]]})
    assert is_open(datetime(2026, 10, 16, 23, 0, tzinfo=tz), hours)  # Friday 23:00
    assert is_open(datetime(2026, 10, 17, 1, 30, tzinfo=tz), hours)  # Saturday 01:30, Friday's range
    assert not is_open(datetime(2026, 10, 17, 3, 0, tzinfo=tz), hours)
    assert is_open(datetime(2026, 10, 19, 8, 50, tzinfo=tz), hours, grace_minutes=15)
    with pytest.raises(ValueError):
        validate_hours({"funday": []})
    with pytest.raises(ValueError):
        validate_hours({"mon": [["9am", "5pm"]]})


def test_rule_params_are_validated():
    assert validate_params("traffic_frequency", {"max_events": 10})["max_events"] == 10
    for bad in ({"max_events": -1}, {"unknown": 1}, {"max_events": "ten"}):
        with pytest.raises(ValueError):
            validate_params("traffic_frequency", bad)


# -- event-driven rules -------------------------------------------------------------------------------

def _record(camera, kind, track, t):
    return EventRecorder().record(camera, "s1", CrossingEvent(kind, track, t, 0.8, (0, 0, 10, 20)), None)


def _alerts():
    with db.session_scope() as s:
        return [(a.rule_type, a.status, a.occurrences, json.loads(a.metrics), a.reason) for a in s.scalars(select(Alert).order_by(Alert.created_at))]


def test_after_hours_entry_raises_explainable_alert(camera, users):
    with db.session_scope() as s:
        s.get(Location, 1).business_hours = json.dumps({d: [["09:00", "09:01"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
    ev = _record(camera, "entry", 1, time.time())
    alert_engine.on_event_recorded(ev)
    alerts = _alerts()
    assert [a[0] for a in alerts] == ["after_hours"]
    assert "outside" in alerts[0][4] and "local_time" in alerts[0][3]


def test_no_business_hours_means_no_after_hours_alert(camera, users):
    alert_engine.on_event_recorded(_record(camera, "entry", 1, time.time()))
    assert _alerts() == []


def test_repeated_crossings_by_one_track(camera, users):
    now = time.time()
    for i, kind in enumerate(["entry", "exit", "entry", "exit"]):
        ev = _record(camera, kind, 9, now - 60 + i * 10)
        alert_engine.on_event_recorded(ev)
    alerts = [a for a in _alerts() if a[0] == "repeated_crossings"]
    assert len(alerts) == 1 and alerts[0][3]["crossings"] == 4


def test_traffic_frequency_and_dedup(camera, users):
    with db.session_scope() as s:
        save_rule(s, 1, "traffic_frequency", True, None, None, {"max_events": 3, "window_minutes": 10})
    now = time.time()
    for i in range(6):
        alert_engine.on_event_recorded(_record(camera, "entry", 100 + i, now - 30 + i))
    alerts = [a for a in _alerts() if a[0] == "traffic_frequency"]
    assert len(alerts) == 1  # one open alert, updated rather than duplicated
    assert alerts[0][2] == 3 and alerts[0][3]["events_in_window"] == 6


def test_occupancy_over_capacity(camera, users):
    with db.session_scope() as s:
        s.get(Location, 1).capacity = 2
    now = time.time()
    for i in range(3):
        alert_engine.on_event_recorded(_record(camera, "entry", 200 + i, now - 10 + i))
    alerts = [a for a in _alerts() if a[0] == "occupancy"]
    assert alerts and alerts[0][3]["occupancy"] == 3 and alerts[0][3]["capacity"] == 2


def test_disabled_rule_does_not_fire(camera, users):
    with db.session_scope() as s:
        s.get(Location, 1).business_hours = json.dumps({"mon": [["09:00", "09:01"]]})
        save_rule(s, 1, "after_hours", False, None, None, None)
    alert_engine.on_event_recorded(_record(camera, "entry", 1, time.time()))
    assert _alerts() == []


# -- zone alerts with evidence -----------------------------------------------------------------------

def test_restricted_zone_alert_has_snapshot_and_dedups(camera, users, snapshot_dir, client):
    from models.entities import CameraZone
    from vision.zones import ZoneEvent

    with db.session_scope() as s:
        zone = CameraZone(organization_id=1, camera_id=camera, name="Stock room", kind="restricted", polygon=json.dumps([list(p) for p in SQUARE]))
        s.add(zone)
        s.flush()
        zone_id = zone.id
    spec = CameraSpec(id=camera, name="Main Entrance", source_type="browser", source=None, line=None, organization_id=1, location_id=1)
    for track in (1, 2):
        ev = ZoneEvent("zone_entered", zone_id, "Stock room", "restricted", track, time.time(), 1.0, 0.8, (0, 0, 10, 10))
        alert_engine.on_zone_event(spec, "sess", ev, b"\xff\xd8zone-jpeg")
    with db.session_scope() as s:
        alerts = list(s.scalars(select(Alert)))
        assert len(alerts) == 1 and alerts[0].occurrences == 2 and alerts[0].snapshot_status == "saved"
        assert alerts[0].snapshot_path.startswith("org_1/alerts/")
        alert_id = alerts[0].id
    login(client, "operator", users["operator"])
    r = client.get(f"/api/v1/alerts/{alert_id}/snapshot")
    assert r.status_code == 200 and r.content == b"\xff\xd8zone-jpeg"
    assert "Track 1 (temporary)" in client.get(f"/api/v1/alerts/{alert_id}").json()["reason"]


# -- periodic rules ---------------------------------------------------------------------------------

class FakeWorker:
    def __init__(self, spec, status="live", quality=None, detection_status="active"):
        self.spec, self.status, self.quality = spec, status, quality
        self.detection_status, self.detection_message = detection_status, "Detection failed on a frame: RuntimeError"


def test_camera_offline_alert_and_auto_resolve(camera, users):
    with db.session_scope() as s:
        s.add(CameraIncident(organization_id=1, camera_id=camera, kind="disconnected", message="No frames",
                             started_at=db.utcnow() - timedelta(minutes=5)))
    engine = alert_engine.AlertEngine()
    engine.check_camera_offline()
    assert [(a[0], a[1]) for a in _alerts()] == [("camera_offline", "new")]
    with db.session_scope() as s:
        for inc in s.scalars(select(CameraIncident)):
            inc.ended_at = db.utcnow()
    engine.check_camera_offline()
    assert [(a[0], a[1]) for a in _alerts()] == [("camera_offline", "resolved")]


def test_camera_quality_needs_sustained_degradation(camera, users):
    spec = CameraSpec(id=camera, name="Main Entrance", source_type="browser", source=None, line=None, organization_id=1, location_id=1)
    clock = [1000.0]
    worker = FakeWorker(spec, quality={"brightness": 2.0, "contrast": 1.0, "sharpness": 0.5, "measured_at": 0})
    engine = alert_engine.AlertEngine(workers=lambda: [worker], clock=lambda: clock[0])
    engine.check_camera_quality()
    assert _alerts() == []
    clock[0] += 200
    engine.check_camera_quality()
    alerts = _alerts()
    assert alerts[0][0] == "camera_quality" and "very dark" in alerts[0][4]
    worker.quality = {"brightness": 120.0, "contrast": 50.0, "sharpness": 300.0, "measured_at": 0}
    engine.check_camera_quality()
    assert _alerts()[0][1] == "resolved"


def test_processing_error_for_failing_detector_and_pending_writes(camera, users):
    spec = CameraSpec(id=camera, name="Main Entrance", source_type="browser", source=None, line=None, organization_id=1, location_id=1)
    clock = [0.0]
    pending = {1: 4}
    engine = alert_engine.AlertEngine(workers=lambda: [FakeWorker(spec, detection_status="error")], pending_events=lambda: pending,
                                      clock=lambda: clock[0])
    engine.check_processing()
    clock[0] = 120
    engine.check_processing()
    titles = sorted(a[4][:20] for a in _alerts())
    assert len(titles) == 2
    pending.clear()
    engine.check_processing()
    statuses = {a[0]: a[1] for a in _alerts() if "waiting to be written" in a[4]}
    assert statuses == {"processing_error": "resolved"}


# -- review workflow ---------------------------------------------------------------------------------

def _make_alert():
    with db.session_scope() as s:
        outcome = raise_alert(s, AlertDraft(1, "after_hours", "operations", "medium", "After hours", "reason", "k1",
                                            db.utcnow(), metrics={"a": 1}, location_id=1), 900)
        return outcome.alert.id


def test_review_workflow_via_api(client, users):
    alert_id = _make_alert()
    login(client, "operator", users["operator"])
    r = client.post(f"/api/v1/alerts/{alert_id}/actions", json={"action": "acknowledge"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["acknowledged_by"] == "operator"
    r = client.post(f"/api/v1/alerts/{alert_id}/actions", json={"action": "resolve", "note": "Cleaner working late"}, headers=CSRF)
    assert r.json()["status"] == "resolved" and r.json()["resolution_note"] == "Cleaner working late"
    assert client.post(f"/api/v1/alerts/{alert_id}/actions", json={"action": "dismiss"}, headers=CSRF).status_code == 409
    detail = client.get(f"/api/v1/alerts/{alert_id}").json()
    assert [a["action"] for a in detail["audit"]] == ["alert.resolve", "alert.acknowledge"]
    assert client.get("/api/v1/alerts?status=open").json()["total"] == 0
    assert client.get("/api/v1/alerts?status=resolved").json()["total"] == 1


def test_cooldown_controls_renotification():
    with db.session_scope() as s:
        first = raise_alert(s, AlertDraft(1, "camera_offline", "camera_health", "high", "t", "r", "dedup", db.utcnow()), 3600)
        second = raise_alert(s, AlertDraft(1, "camera_offline", "camera_health", "high", "t", "r", "dedup", db.utcnow()), 3600)
        escalated = raise_alert(s, AlertDraft(1, "camera_offline", "camera_health", "critical", "t", "r", "dedup", db.utcnow()), 3600)
        assert first.created and first.notify
        assert not second.created and not second.notify
        assert escalated.notify and escalated.alert.severity == "critical"


# -- notifications -----------------------------------------------------------------------------------

def _channel(kind="webhook", min_severity="medium", rate=30):
    with db.session_scope() as s:
        ch = NotificationChannel(organization_id=1, kind=kind, name="Ops", min_severity=min_severity, rate_limit_per_hour=rate, config_secret="")
        cfg = {"url": "https://hooks.example.com/x", "secret": "s" * 20} if kind == "webhook" else {"recipients": ["owner@example.com"]}
        notifications.store_config(ch, cfg)
        s.add(ch)
        s.flush()
        return ch.id


def _queue(severity):
    with db.session_scope() as s:
        out = raise_alert(s, AlertDraft(1, "after_hours", "operations", severity, "t", "r", f"k-{severity}-{time.time()}", db.utcnow()), 900)
        return notifications.queue_alert_notifications(s, out.alert)


def test_channel_severity_filter_and_retry_backoff():
    _channel(min_severity="high")
    assert _queue("low") == 0
    assert _queue("high") == 1
    calls = []

    def failing(delivery, channel):
        calls.append(delivery.id)
        raise notifications.ChannelError("Webhook endpoint answered HTTP 500.")

    assert notifications.process_pending(sender=failing) == 1
    with db.session_scope() as s:
        d = s.scalar(select(NotificationDelivery))
        assert d.status == "pending" and d.attempts == 1 and d.next_attempt_at > db.utcnow() + timedelta(seconds=20)
        assert d.last_error == "Webhook endpoint answered HTTP 500."
        d.next_attempt_at = db.utcnow()
    assert notifications.process_pending(sender=lambda d, c: None) == 1
    with db.session_scope() as s:
        assert s.scalar(select(NotificationDelivery)).status == "sent"


def test_delivery_gives_up_after_max_attempts():
    _channel()
    _queue("high")

    def failing(delivery, channel):
        raise RuntimeError("boom with https://secret-token@hooks")

    for _ in range(notifications.MAX_ATTEMPTS):
        with db.session_scope() as s:
            for d in s.scalars(select(NotificationDelivery)):
                d.next_attempt_at = db.utcnow()
        notifications.process_pending(sender=failing)
    with db.session_scope() as s:
        d = s.scalar(select(NotificationDelivery))
        assert d.status == "failed" and d.last_error == "RuntimeError"  # exception text (may hold secrets) not stored


def test_rate_limit_suppresses_excess():
    _channel(rate=2)
    for _ in range(4):
        _queue("high")
    notifications.process_pending(sender=lambda d, c: None)
    with db.session_scope() as s:
        statuses = sorted(d.status for d in s.scalars(select(NotificationDelivery)))
    assert statuses == ["sent", "sent", "suppressed", "suppressed"]


def test_webhook_signature():
    body = b'{"a":1}'
    import hashlib
    import hmac

    assert notifications.sign("k" * 16, body) == "sha256=" + hmac.new(b"k" * 16, body, hashlib.sha256).hexdigest()


def test_channel_api_never_returns_secrets(client, users, monkeypatch):
    monkeypatch.setattr(notifications, "_check_webhook_destination", lambda url: None)
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/notification-channels", json={
        "kind": "webhook", "name": "Ops", "url": "https://hooks.example.com/path/token123", "secret": "very-secret-signing-key"}, headers=CSRF)
    assert r.status_code == 201, r.text
    assert "very-secret-signing-key" not in r.text and "token123" not in r.text
    r = client.post("/api/v1/notification-channels", json={"kind": "email", "name": "Owner", "recipients": ["owner@example.com"]}, headers=CSRF)
    assert r.status_code == 201 and "owner@example.com" not in r.text
    listing = client.get("/api/v1/notification-channels").text
    assert "very-secret-signing-key" not in listing and "owner@example.com" not in listing
    assert client.post("/api/v1/notification-channels", json={"kind": "email", "name": "x", "recipients": ["not-an-email"]}, headers=CSRF).status_code == 422


def test_webhook_to_private_or_metadata_address_refused():
    for url in ("https://169.254.169.254/latest", "http://127.0.0.1:8000/x", "https://192.168.1.10/hook"):
        with pytest.raises(notifications.ChannelError):
            notifications.validate_webhook_url(url)


def test_rule_configuration_api(client, users):
    login(client, "admin", users["admin"])
    rules = client.get("/api/v1/alert-rules").json()
    assert {r["rule_type"] for r in rules} >= {"restricted_zone", "after_hours", "camera_offline", "ml_anomaly"}
    r = client.put("/api/v1/alert-rules/traffic_frequency", json={"enabled": False, "severity": "high", "params": {"max_events": 5}}, headers=CSRF)
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["params"]["max_events"] == 5
    assert client.put("/api/v1/alert-rules/traffic_frequency", json={"params": {"max_events": -3}}, headers=CSRF).status_code == 422
    assert client.put("/api/v1/alert-rules/nope", json={}, headers=CSRF).status_code == 404
