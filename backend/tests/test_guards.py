"""Camera guards (posts and duties), the head guard (incidents, corroboration, escalation, briefing)
and the console-managed mail server. All alerts are synthetic; no network calls are made."""

import json
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

import db
from models.entities import Alert, Camera, GuardIncident, NotificationChannel, NotificationDelivery
from services import alert_engine, alerts as alert_service, guards, head_guard, mail_server, notifications
from services.alert_rules import RULES
from services.alerts import AlertDraft, publish, raise_alert
from tests.conftest import CSRF, LOCATION, ORG, login


@pytest.fixture(autouse=True)
def clean_caches():
    alert_engine._rule_cache.clear()
    guards.invalidate()
    previous = alert_service.report_hook
    alert_service.report_hook = head_guard.on_report
    yield
    alert_service.report_hook = previous


def _cam(cam_id, post=None, duties=None, name=None):
    with db.session_scope() as s:
        s.add(Camera(id=cam_id, organization_id=ORG, location_id=LOCATION, name=name or cam_id, location=f"{cam_id} spot",
                     source_type="browser", guard_post=post, guard_duties=json.dumps(duties) if duties is not None else None))
    guards.invalidate()
    return cam_id


def _channel(kind="email", min_severity="low"):
    with db.session_scope() as s:
        ch = NotificationChannel(organization_id=ORG, kind=kind, name=f"Owner {kind}", min_severity=min_severity, rate_limit_per_hour=30, config_secret="")
        notifications.store_config(ch, {"recipients": ["owner@example.com"]} if kind == "email" else {"bot_token": "1", "chat_id": "2"})
        s.add(ch)
        s.flush()
        return ch.id


def _report(rule_type, camera_id, severity=None, key=None):
    d = RULES[rule_type]
    draft = AlertDraft(ORG, rule_type, d.category, severity or d.severity, d.title, f"{d.title} on {camera_id}",
                       key or f"{rule_type}:{camera_id}:{time.time()}", db.utcnow(), camera_id=camera_id, location_id=LOCATION)
    return alert_engine._emit(draft, alert_engine.rules_for(ORG)[rule_type])


def _deliveries():
    with db.session_scope() as s:
        return [(d.kind, d.subject) for d in s.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id))]


def _incidents():
    with db.session_scope() as s:
        return [(i.title, i.severity, i.status, json.loads(i.camera_ids), i.report_count) for i in s.scalars(select(GuardIncident))]


# -- duties ------------------------------------------------------------------------------------------

def test_unassigned_camera_keeps_every_duty():
    _cam("CAM-A")
    for rule in ("restricted_zone", "zone_dwell", "after_hours", "video_anomaly_model", "repeated_crossings"):
        assert guards.guard_allows(ORG, "CAM-A", rule)


def test_corridor_guard_reports_fights_but_not_gate_rules():
    _cam("CAM-CORR", post="corridor")
    assert guards.guard_allows(ORG, "CAM-CORR", "video_anomaly_model")
    assert guards.guard_allows(ORG, "CAM-CORR", "zone_dwell")
    assert not guards.guard_allows(ORG, "CAM-CORR", "after_hours")
    assert not guards.guard_allows(ORG, "CAM-CORR", "restricted_zone")
    # A guard always reports that it cannot see.
    assert guards.guard_allows(ORG, "CAM-CORR", "camera_offline")
    assert _report("after_hours", "CAM-CORR") is None
    assert _report("video_anomaly_model", "CAM-CORR") is not None


def test_custom_duties_override_post_and_default_is_stored_as_null():
    cam_id = _cam("CAM-G", post="main_gate")
    with db.session_scope() as s:
        cam = s.get(Camera, cam_id)
        guards.assign(s, cam, "Ramesh (gate)", None, ["gate_log"])
        assert json.loads(cam.guard_duties) == ["gate_log"]
        guards.assign(s, cam, None, None, list(guards.POSTS["main_gate"].duties))
        assert cam.guard_duties is None
        with pytest.raises(guards.GuardError):
            guards.assign(s, cam, None, None, [])
        with pytest.raises(guards.GuardError):
            guards.assign(s, cam, None, "moon_base", None)


# -- head guard --------------------------------------------------------------------------------------

def test_reports_at_one_location_form_one_incident_and_two_guards_raise_severity():
    _cam("CAM-1", post="corridor")
    _cam("CAM-2", post="corridor")
    _channel()
    _report("zone_dwell", "CAM-1")  # medium
    assert _incidents()[0][1] == "medium"
    _report("zone_dwell", "CAM-2")
    (title, severity, status, cams, count), = _incidents()
    assert cams == ["CAM-1", "CAM-2"] and count == 2
    assert severity == "high"  # corroborated by a second guard
    kinds = [k for k, _ in _deliveries()]
    # One message when the incident started, one when the second guard confirmed it; no per-alert messages.
    assert kinds == ["incident", "incident"]


def test_head_guard_escalates_once_per_change_not_per_repeat():
    _cam("CAM-1", post="restricted")
    _channel()
    key = "restricted_zone:7"
    _report("restricted_zone", "CAM-1", key=key)
    _report("restricted_zone", "CAM-1", key=key)  # same open alert, inside cooldown
    _report("restricted_zone", "CAM-1", key=key)
    assert len(_deliveries()) == 1
    assert _incidents()[0][4] == 3


def test_system_reports_do_not_merge_with_security_incidents():
    _cam("CAM-1")
    _report("video_anomaly_model", "CAM-1")
    _report("camera_offline", "CAM-1")
    assert len(_incidents()) == 2


def test_incident_text_has_actions_and_disclaimer():
    _cam("CAM-1", post="corridor", name="2F corridor")
    _report("video_anomaly_model", "CAM-1")
    with db.session_scope() as s:
        inc = s.scalar(select(GuardIncident))
        text = head_guard.incident_text(s, inc)
    assert "Possible fight" in text and "What to do next" in text and "2F corridor" in text
    assert "does not identify anyone" in text


def test_disabled_head_guard_falls_back_to_per_alert_notifications():
    _cam("CAM-1")
    _channel()
    with db.session_scope() as s:
        head_guard.save_config(s, ORG, {"enabled": False})
    _report("restricted_zone", "CAM-1")
    assert [k for k, _ in _deliveries()] == ["alert"]
    assert _incidents() == []


def test_config_validation():
    with db.session_scope() as s:
        with pytest.raises(ValueError):
            head_guard.save_config(s, ORG, {"correlation_minutes": 0})
        with pytest.raises(ValueError):
            head_guard.save_config(s, ORG, {"briefing_hour": 24})
        with pytest.raises(ValueError):
            head_guard.save_config(s, ORG, {"unknown": 1})
        assert head_guard.save_config(s, ORG, {"briefing_enabled": True, "briefing_hour": 7})["briefing_hour"] == 7


def test_quiet_incident_with_closed_reports_auto_resolves():
    _cam("CAM-1")
    alert_id = _report("restricted_zone", "CAM-1")
    with db.session_scope() as s:
        s.get(Alert, alert_id).status = "resolved"
        s.scalar(select(GuardIncident)).last_seen_at = db.utcnow() - timedelta(hours=5)
    head_guard.tick()
    assert _incidents()[0][2] == "resolved"


def test_daily_briefing_goes_to_every_channel_once():
    _cam("CAM-1")
    _channel("email")
    _channel("telegram")
    with db.session_scope() as s:
        from services.site_settings import get_site_settings, site_zone

        local_hour = db.utcnow().astimezone(site_zone(get_site_settings(s, ORG))).hour
        head_guard.save_config(s, ORG, {"briefing_enabled": True, "briefing_hour": local_hour})
    head_guard.tick()
    head_guard.tick()
    assert [k for k, _ in _deliveries()] == ["briefing", "briefing"]


# -- API ---------------------------------------------------------------------------------------------

def test_guard_room_api_roster_assignment_and_incident_review(client):
    _cam("CAM-1", name="Main gate")
    _channel()
    login(client, "admin", "AdminPass123")
    room = client.get("/api/v1/guard-room").json()
    assert room["guards"][0]["post"] == "general" and room["guards"][0]["state"] == "off_duty"
    assert room["capacity"]["max_cameras_per_server"] >= 16
    assert any("off duty" in r["text"] for r in room["recommendations"])

    r = client.put("/api/v1/guards/CAM-1", json={"post": "main_gate", "guard_name": "Gate guard"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["post"] == "main_gate" and "fight" in r.json()["duties"]
    assert client.put("/api/v1/guards/CAM-1", json={"duties": ["teleport"]}, headers=CSRF).status_code == 422

    _report("video_anomaly_model", "CAM-1")
    inc = client.get("/api/v1/guard-room").json()["incidents"][0]
    assert inc["guards"][0]["guard_name"] == "Gate guard" and inc["actions"]
    r = client.post(f"/api/v1/guard-incidents/{inc['id']}", json={"action": "acknowledge"}, headers=CSRF)
    assert r.json()["status"] == "acknowledged"
    r = client.post(f"/api/v1/guard-incidents/{inc['id']}", json={"action": "resolve", "note": "Students were playing"}, headers=CSRF)
    assert r.json()["status"] == "resolved"
    assert client.post(f"/api/v1/guard-incidents/{inc['id']}", json={"action": "resolve"}, headers=CSRF).status_code == 409


def test_viewer_cannot_open_guard_room_and_operator_cannot_assign(client):
    _cam("CAM-1")
    login(client, "viewer", "ViewerPass123")
    assert client.get("/api/v1/guard-room").status_code == 403
    login(client, "operator", "OperatorPass123")
    assert client.get("/api/v1/guard-room").status_code == 200
    assert client.put("/api/v1/guards/CAM-1", json={"post": "corridor"}, headers=CSRF).status_code == 403


def test_mail_server_is_encrypted_never_returns_password_and_is_used_for_email(client, monkeypatch):
    login(client, "admin", "AdminPass123")
    assert client.get("/api/v1/mail-server").json()["configured"] is False
    body = {"host": "smtp.gmail.com", "port": 587, "security": "starttls", "username": "pg.owner@gmail.com",
            "password": "abcd efgh ijkl mnop", "from_address": "pg.owner@gmail.com", "from_name": "Sunrise PG Security"}
    r = client.put("/api/v1/mail-server", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "console" and data["has_password"] and "password" not in data
    with db.session_scope() as s:
        from services.site_settings import get_site_settings

        stored = get_site_settings(s, ORG).mail_config_secret
    assert "abcd" not in stored and "gmail" not in stored

    # Saving without a password keeps the stored one.
    client.put("/api/v1/mail-server", json={**body, "password": None, "from_name": "PG"}, headers=CSRF)
    assert mail_server.effective_config(ORG).password == "abcd efgh ijkl mnop"

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append((host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            sent.append("tls")

        def login(self, user, password):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(msg["From"])

    monkeypatch.setattr(mail_server.smtplib, "SMTP", FakeSMTP)
    r = client.post("/api/v1/mail-server/test", json={"to": "owner@example.com"}, headers=CSRF)
    assert r.status_code == 200, r.text
    assert sent == [("smtp.gmail.com", 587), "tls", ("login", "pg.owner@gmail.com"), "PG <pg.owner@gmail.com>"]

    bad = client.put("/api/v1/mail-server", json={**body, "host": "not a host"}, headers=CSRF)
    assert bad.status_code == 422
    assert client.delete("/api/v1/mail-server", headers=CSRF).status_code == 204
    assert client.get("/api/v1/mail-server").json()["configured"] is False


def test_fight_duty_controls_video_model_feed():
    from vision.camera_worker import CameraSpec

    _cam("CAM-ROOF", post="restricted")
    with db.session_scope() as s:
        assert guards.watches_fights(s.get(Camera, "CAM-ROOF")) is False
    assert CameraSpec("X", "X", "browser", None, None).fight_watch is True
