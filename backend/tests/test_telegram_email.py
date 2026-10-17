"""Telegram and email delivery: snapshot opt-in, secrecy of tokens, and .env channel bootstrap.
No real network calls: httpx/smtplib are replaced with fakes."""

import json

import pytest
from sqlalchemy import select

import db
from models.entities import NotificationChannel, NotificationDelivery
from services import notifications
from services.alerts import AlertDraft, raise_alert
from tests.conftest import CSRF, login

TOKEN = "123456789:" + "A" * 35


class FakeResponse:
    def __init__(self, status):
        self.status_code = status


class Calls(list):
    """Recorded fake HTTP calls; `status` is the HTTP status the fake returns."""

    status = None


@pytest.fixture
def sent(monkeypatch):
    calls = Calls()

    def fake_post(url, data=None, files=None, timeout=None, **kw):
        calls.append({"url": url, "data": data, "files": files})
        return FakeResponse(sent_status[0])

    sent_status = [200]
    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    calls.status = sent_status
    return calls


def _channel(kind, attach):
    with db.session_scope() as s:
        ch = NotificationChannel(organization_id=1, kind=kind, name=kind, min_severity="low", config_secret="")
        cfg = notifications.build_config(kind, ["owner@example.com"] if kind == "email" else None, None, None,
                                         bot_token=TOKEN if kind == "telegram" else None, chat_id="987654321" if kind == "telegram" else None,
                                         attach_snapshot=attach)
        notifications.store_config(ch, cfg)
        s.add(ch)


def _alert_with_snapshot(snapshot_dir):
    from datetime import datetime, timezone

    from services.snapshots import save_snapshot

    rel, status = save_snapshot("a1", datetime.now(timezone.utc), b"\xff\xd8evidence", 1, 0, kind="alerts")
    with db.session_scope() as s:
        out = raise_alert(s, AlertDraft(1, "video_anomaly_model", "video_model", "high", "Vigorous movement between people",
                                        "reason text", "k", db.utcnow(), camera_id=None, snapshot_path=rel, snapshot_status=status), 600)
        notifications.queue_alert_notifications(s, out.alert)


@pytest.mark.parametrize("attach", [True, False])
def test_telegram_sends_photo_only_when_opted_in(sent, snapshot_dir, attach):
    _channel("telegram", attach)
    _alert_with_snapshot(snapshot_dir)
    notifications.process_pending()
    assert len(sent) == 1
    call = sent[0]
    assert call["url"].endswith("/sendPhoto" if attach else "/sendMessage")
    assert call["data"]["chat_id"] == "987654321"
    text = call["data"].get("caption") or call["data"].get("text")
    assert "Vigorous movement between people" in text and "not proof" in text
    if attach:
        assert call["files"]["photo"][1] == b"\xff\xd8evidence"
    with db.session_scope() as s:
        assert s.scalar(select(NotificationDelivery)).status == "sent"


def test_telegram_error_never_stores_the_token(sent, snapshot_dir):
    sent.status[0] = 401
    _channel("telegram", False)
    _alert_with_snapshot(snapshot_dir)
    notifications.process_pending()
    with db.session_scope() as s:
        d = s.scalar(select(NotificationDelivery))
        assert d.status == "pending" and "bot token" in d.last_error and TOKEN not in d.last_error


def test_email_attaches_snapshot_when_opted_in(monkeypatch, snapshot_dir):
    from config import settings

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_FROM", "alerts@example.com")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", False)
    messages = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            messages.append(msg)

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    _channel("email", True)
    _alert_with_snapshot(snapshot_dir)
    notifications.process_pending()
    assert len(messages) == 1
    attachments = [p for p in messages[0].iter_attachments()]
    assert attachments and attachments[0].get_content_type() == "image/jpeg"


def test_validation_and_api_secrecy(client, users):
    with pytest.raises(notifications.ChannelError):
        notifications.build_config("telegram", None, None, None, bot_token="not-a-token", chat_id="123")
    with pytest.raises(notifications.ChannelError):
        notifications.build_config("webhook", None, "https://x.example.com", "s" * 20, attach_snapshot=True)
    login(client, "admin", users["admin"])
    r = client.post("/api/v1/notification-channels", json={"kind": "telegram", "name": "Owner phone", "bot_token": TOKEN,
                                                            "chat_id": "987654321", "attach_snapshot": True, "min_severity": "high"}, headers=CSRF)
    assert r.status_code == 201, r.text
    assert TOKEN not in r.text and r.json()["attach_snapshot"] is True and r.json()["target"] == "Telegram chat …4321"
    assert TOKEN not in client.get("/api/v1/notification-channels").text


def test_channels_from_env(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "owner@example.com, manager@example.com")
    assert sorted(notifications.ensure_env_channels()) == ["Email (from .env)", "Telegram (from .env)"]
    assert len(notifications.ensure_env_channels()) == 2  # idempotent: updates, never duplicates
    with db.session_scope() as s:
        rows = list(s.scalars(select(NotificationChannel)))
        assert len(rows) == 2
        cfg = notifications.channel_config(next(r for r in rows if r.kind == "email"))
        assert cfg["recipients"] == ["manager@example.com", "owner@example.com"] and cfg["attach_snapshot"] is True
