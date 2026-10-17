"""
Notification channels and delivery.

In-app notification is always on: every alert is pushed over the organization's WebSocket and
listed on the Alerts page. Additional channels (email, Telegram, webhook) are configured per organization:

- min_severity and an optional category list decide which alerts a channel receives,
- rate_limit_per_hour caps deliveries per channel; excess deliveries are marked "suppressed",
- failed deliveries are retried with bounded exponential backoff (MAX_ATTEMPTS),
- webhook bodies are signed: X-VV-Signature: sha256=<HMAC of the body with the channel secret>,
- channel secrets, bot tokens and recipient lists are encrypted at rest and never returned by the API,
- evidence snapshots are attached to email/Telegram messages only when the channel opts in
  ("attach_snapshot"); webhooks never carry images.
"""

import hashlib
import hmac
import json
import logging
import re
import smtplib
import ssl
import threading
from datetime import timedelta
from email.message import EmailMessage
from typing import Callable, List, Optional
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import settings
from db import session_scope, utcnow
from models.entities import Alert, NotificationChannel, NotificationDelivery
from services.alerts import SEVERITY_RANK
from services.secretbox import SecretError, decrypt_json, encrypt_json

logger = logging.getLogger("viahind.notifications")

PURPOSE = "notification-channel"
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (30, 120, 600, 1800, 7200)
EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,}$")
TELEGRAM_TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,60}$")
TELEGRAM_CHAT = re.compile(r"^(-?\d{3,20}|@[A-Za-z0-9_]{5,32})$")
TELEGRAM_API = "https://api.telegram.org"


class ChannelError(ValueError):
    pass


# -- configuration -----------------------------------------------------------------------------

def validate_webhook_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ChannelError("Webhook URLs must be http(s):// URLs.")
    if settings.IS_PRODUCTION and parts.scheme != "https":
        raise ChannelError("Webhook URLs must use https:// in production.")
    if parts.username or parts.password:
        raise ChannelError("Put webhook credentials in the signing secret, not in the URL.")
    _check_webhook_destination(url)
    return url


def _check_webhook_destination(url: str) -> None:
    import ipaddress
    import socket

    parts = urlsplit(url)
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise ChannelError("The webhook host name could not be resolved.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise ChannelError("Webhooks to loopback, link-local or reserved addresses are not allowed.")
        if ip.is_private and not settings.WEBHOOK_ALLOW_PRIVATE:
            raise ChannelError("Webhooks to private network addresses need WEBHOOK_ALLOW_PRIVATE=True on the server.")


def build_config(kind: str, recipients: Optional[List[str]], url: Optional[str], secret: Optional[str], existing: Optional[dict] = None,
                 bot_token: Optional[str] = None, chat_id: Optional[str] = None, attach_snapshot: Optional[bool] = None) -> dict:
    config = dict(existing or {})
    if attach_snapshot is not None:
        if kind == "webhook" and attach_snapshot:
            raise ChannelError("Webhooks never carry images; link to the console instead.")
        config["attach_snapshot"] = bool(attach_snapshot)
    if kind == "telegram":
        if bot_token is not None:
            if not TELEGRAM_TOKEN.match(bot_token.strip()):
                raise ChannelError("That does not look like a Telegram bot token (123456789:ABC…) from @BotFather.")
            config["bot_token"] = bot_token.strip()
        if chat_id is not None:
            if not TELEGRAM_CHAT.match(chat_id.strip()):
                raise ChannelError("The chat ID is a number (e.g. 123456789 or -1001234567890 for a group) or @channelname.")
            config["chat_id"] = chat_id.strip()
        if not config.get("bot_token") or not config.get("chat_id"):
            raise ChannelError("A Telegram channel needs a bot token and a chat ID.")
        return config
    if kind == "email":
        if recipients is not None:
            cleaned = sorted({r.strip().lower() for r in recipients if r.strip()})
            if not cleaned or len(cleaned) > 20 or not all(EMAIL.match(r) for r in cleaned):
                raise ChannelError("Enter 1-20 valid email addresses.")
            config["recipients"] = cleaned
        if not config.get("recipients"):
            raise ChannelError("Enter at least one recipient.")
    elif kind == "webhook":
        if url is not None:
            config["url"] = validate_webhook_url(url)
        if secret is not None:
            if len(secret) < 16:
                raise ChannelError("The signing secret must be at least 16 characters.")
            config["secret"] = secret
        if not config.get("url") or not config.get("secret"):
            raise ChannelError("A webhook needs a URL and a signing secret.")
    else:
        raise ChannelError("Unknown channel type.")
    return config


def channel_config(channel: NotificationChannel) -> dict:
    return decrypt_json(PURPOSE, channel.config_secret)


def store_config(channel: NotificationChannel, config: dict) -> None:
    channel.config_secret = encrypt_json(PURPOSE, config)


def serialize_channel(channel: NotificationChannel) -> dict:
    try:
        config = channel_config(channel)
        if channel.kind == "email":
            recipients = config.get("recipients", [])
            target = ", ".join(_mask_email(r) for r in recipients)
        elif channel.kind == "telegram":
            chat = str(config.get("chat_id", ""))
            target = f"Telegram chat …{chat[-4:]}" if not chat.startswith("@") else f"Telegram {chat}"
        else:
            parts = urlsplit(config.get("url", ""))
            target = f"{parts.scheme}://{parts.hostname}{'/…' if parts.path not in ('', '/') else ''}"
        config_ok = True
    except SecretError as exc:
        target, config_ok = str(exc), False
    return {
        "id": channel.id,
        "kind": channel.kind,
        "name": channel.name,
        "enabled": channel.enabled,
        "min_severity": channel.min_severity,
        "categories": json.loads(channel.categories) if channel.categories else None,
        "rate_limit_per_hour": channel.rate_limit_per_hour,
        "target": target,
        "config_ok": config_ok,
        "attach_snapshot": bool(config.get("attach_snapshot")) if config_ok else False,
    }


def _mask_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return (local[:2] + "***@" + domain) if local else address


# -- queueing ----------------------------------------------------------------------------------

def _wants(channel: NotificationChannel, alert: Alert) -> bool:
    if not channel.enabled or SEVERITY_RANK.get(alert.severity, 0) < SEVERITY_RANK.get(channel.min_severity, 0):
        return False
    if channel.categories:
        try:
            return alert.category in json.loads(channel.categories)
        except json.JSONDecodeError:
            return True
    return True


def alert_payload(alert: Alert, db: Session) -> dict:
    from services.alerts import serialize_alert

    data = serialize_alert(alert, db, include_snapshot=False)
    # Evidence images are never sent to external channels; link to the console instead.
    if settings.PUBLIC_BASE_URL:
        data["url"] = settings.PUBLIC_BASE_URL.rstrip("/") + f"/alerts?id={alert.id}"
    return data


def queue_alert_notifications(db: Session, alert: Alert) -> int:
    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == alert.organization_id))
    payload = None
    n = 0
    for channel in channels:
        if not _wants(channel, alert):
            continue
        payload = payload or alert_payload(alert, db)
        db.add(NotificationDelivery(
            organization_id=alert.organization_id, alert_id=alert.id, channel_id=channel.id, kind="alert",
            subject=f"[{alert.severity.upper()}] {alert.title}", payload=json.dumps(payload, default=str),
            status="pending", next_attempt_at=utcnow(),
        ))
        n += 1
    return n


def queue_message(db: Session, channel: NotificationChannel, kind: str, subject: str, payload: dict) -> NotificationDelivery:
    row = NotificationDelivery(
        organization_id=channel.organization_id, channel_id=channel.id, kind=kind, subject=subject[:200],
        payload=json.dumps(payload, default=str), status="pending", next_attempt_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


# -- sending -----------------------------------------------------------------------------------

def _format_text(subject: str, payload: dict) -> str:
    if "text" in payload:
        return str(payload["text"])
    lines = [subject, ""]
    for key in ("reason", "location_name", "camera_name", "zone_name", "first_seen_at", "last_seen_at", "occurrences", "status"):
        if payload.get(key) not in (None, ""):
            lines.append(f"{key.replace('_', ' ').capitalize()}: {payload[key]}")
    metrics = payload.get("metrics") or {}
    if metrics:
        lines.append("")
        lines.append("Measured values:")
        lines.extend(f"  {k}: {v}" for k, v in metrics.items())
    if payload.get("url"):
        lines += ["", f"Review: {payload['url']}"]
    lines += ["", "This alert describes a measured condition for human review. It does not identify anyone or establish wrongdoing."]
    return "\n".join(lines)


def send_email(recipients: List[str], subject: str, body: str, image: Optional[bytes] = None) -> None:
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        raise ChannelError("Email is not configured on the server (SMTP_HOST / SMTP_FROM).")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    if image:
        msg.add_attachment(image, maintype="image", subtype="jpeg", filename="evidence.jpg")
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls(context=ssl.create_default_context())
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send_webhook(url: str, secret: str, delivery_id: int, kind: str, payload: dict) -> None:
    import httpx

    _check_webhook_destination(url)
    body = json.dumps({"type": kind, "delivery_id": delivery_id, "data": payload}, default=str, sort_keys=True).encode("utf-8")
    response = httpx.post(
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "VIAHIND-Vision-Webhook/1",
            "X-VV-Signature": sign(secret, body),
            "X-VV-Delivery": str(delivery_id),
        },
        timeout=10.0,
        follow_redirects=False,
    )
    if response.status_code >= 300:
        raise ChannelError(f"Webhook endpoint answered HTTP {response.status_code}.")


def send_telegram(bot_token: str, chat_id: str, text: str, image: Optional[bytes] = None) -> None:
    """Bot API sendMessage / sendPhoto. Errors never include the token (it is part of the URL)."""
    import httpx

    base = f"{TELEGRAM_API}/bot{bot_token}"
    try:
        if image:
            response = httpx.post(f"{base}/sendPhoto", data={"chat_id": chat_id, "caption": text[:1024]},
                                  files={"photo": ("evidence.jpg", image, "image/jpeg")}, timeout=20.0)
        else:
            response = httpx.post(f"{base}/sendMessage", data={"chat_id": chat_id, "text": text[:4096],
                                                                "disable_web_page_preview": "true"}, timeout=15.0)
    except httpx.HTTPError as exc:
        raise ChannelError(f"Telegram could not be reached ({type(exc).__name__}).") from None
    if response.status_code == 401:
        raise ChannelError("Telegram rejected the bot token (401). Create a new token with @BotFather.")
    if response.status_code == 400 or response.status_code == 403:
        raise ChannelError(f"Telegram refused the message (HTTP {response.status_code}): check the chat ID and that you sent /start to the bot.")
    if response.status_code >= 300:
        raise ChannelError(f"Telegram answered HTTP {response.status_code}.")


def _snapshot_for(delivery: NotificationDelivery) -> Optional[bytes]:
    if not delivery.alert_id:
        return None
    from services.snapshots import snapshot_file
    from models.entities import Alert

    with session_scope() as db:
        alert = db.get(Alert, delivery.alert_id)
        path = snapshot_file(alert.snapshot_path) if alert is not None and alert.snapshot_status == "saved" else None
    try:
        return path.read_bytes() if path is not None else None
    except OSError:
        return None


def _telegram_text(subject: str, payload: dict) -> str:
    if "text" in payload:
        return f"{subject}\n\n{payload['text']}"
    parts = [subject, "", str(payload.get("reason", ""))]
    where = " · ".join(str(payload[k]) for k in ("location_name", "camera_name", "zone_name") if payload.get(k))
    if where:
        parts.append(where)
    if payload.get("url"):
        parts.append(f"Review: {payload['url']}")
    parts.append("For human review; not proof of wrongdoing.")
    return "\n".join(p for p in parts if p is not None)


def deliver(delivery: NotificationDelivery, channel: NotificationChannel) -> None:
    config = channel_config(channel)
    payload = json.loads(delivery.payload or "{}")
    image = _snapshot_for(delivery) if config.get("attach_snapshot") and channel.kind in ("email", "telegram") else None
    if channel.kind == "email":
        send_email(config["recipients"], delivery.subject, _format_text(delivery.subject, payload), image)
    elif channel.kind == "telegram":
        send_telegram(config["bot_token"], config["chat_id"], _telegram_text(delivery.subject, payload), image)
    elif channel.kind == "webhook":
        send_webhook(config["url"], config["secret"], delivery.id, delivery.kind, payload)
    else:
        raise ChannelError("Unknown channel type.")


def _safe_error(exc: Exception) -> str:
    # Never store exception text that could echo URLs with tokens or SMTP credentials.
    if isinstance(exc, (ChannelError, SecretError)):
        return str(exc)[:300]
    return type(exc).__name__


def process_pending(limit: int = 50, sender: Optional[Callable] = None) -> int:
    """Send due deliveries once. Returns how many were attempted.

    Each delivery is claimed and finished in its own short transaction; the network call runs
    outside any transaction so slow mail servers never block event recording.
    """
    sender = sender or deliver
    with session_scope() as db:
        due_ids = list(db.scalars(
            select(NotificationDelivery.id)
            .where(NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= utcnow())
            .order_by(NotificationDelivery.next_attempt_at)
            .limit(limit)
        ))
    attempted = 0
    for delivery_id in due_ids:
        with session_scope() as db:
            delivery = db.get(NotificationDelivery, delivery_id)
            if delivery is None or delivery.status != "pending":
                continue
            channel = db.get(NotificationChannel, delivery.channel_id)
            if channel is None or not channel.enabled:
                delivery.status, delivery.last_error = "suppressed", "Channel disabled or removed."
                continue
            if delivery.kind == "alert" and _sent_last_hour(db, channel.id) >= channel.rate_limit_per_hour:
                delivery.status, delivery.last_error = "suppressed", "Channel rate limit reached; see the Alerts page."
                continue
            delivery.attempts += 1
            # Claim: push the next attempt out so a concurrent dispatcher would not resend it.
            delivery.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[0])
            db.expunge(channel)
            db.flush()
            db.expunge(delivery)
        attempted += 1
        error = None
        try:
            sender(delivery, channel)
        except Exception as exc:  # any delivery failure is retried, never raised
            error = _safe_error(exc)
            logger.warning("Delivery %s via channel %s failed: %s", delivery_id, channel.id, error)
        with session_scope() as db:
            row = db.get(NotificationDelivery, delivery_id)
            if row is None:
                continue
            if error is None:
                row.status, row.sent_at, row.last_error = "sent", utcnow(), None
            else:
                row.last_error = error
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                else:
                    row.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[min(row.attempts - 1, len(BACKOFF_SECONDS) - 1)])
    return attempted


def _sent_last_hour(db: Session, channel_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(NotificationDelivery).where(
            NotificationDelivery.channel_id == channel_id,
            NotificationDelivery.status == "sent",
            NotificationDelivery.sent_at >= utcnow() - timedelta(hours=1),
        )
    ) or 0


def serialize_delivery(row: NotificationDelivery) -> dict:
    return {
        "id": row.id,
        "alert_id": row.alert_id,
        "channel_id": row.channel_id,
        "kind": row.kind,
        "subject": row.subject,
        "status": row.status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "next_attempt_at": row.next_attempt_at.isoformat(),
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat(),
    }


class NotificationDispatcher:
    def __init__(self, interval_seconds: float = 5.0):
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="notifications", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                process_pending()
            except SQLAlchemyError:
                logger.exception("Notification dispatch failed")


def ensure_env_channels() -> List[str]:
    """Create (or update) the default organization's Telegram/email channels from .env, so a
    single-business install can be set up without the UI. Returns the names configured."""
    from models.entities import Organization

    done: List[str] = []
    wanted = []
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        wanted.append(("telegram", "Telegram (from .env)", {"bot_token": settings.TELEGRAM_BOT_TOKEN, "chat_id": settings.TELEGRAM_CHAT_ID}))
    if settings.ALERT_EMAIL_TO:
        wanted.append(("email", "Email (from .env)", {"recipients": [r for r in settings.ALERT_EMAIL_TO.replace(";", ",").split(",") if r.strip()]}))
    if not wanted:
        return done
    severity = settings.ALERT_MIN_SEVERITY if settings.ALERT_MIN_SEVERITY in SEVERITY_RANK else "medium"
    with session_scope() as db:
        org_id = db.scalar(select(Organization.id).where(Organization.slug == "default"))
        if org_id is None:
            return done
        for kind, name, values in wanted:
            try:
                config = build_config(kind, values.get("recipients"), None, None, bot_token=values.get("bot_token"),
                                      chat_id=values.get("chat_id"), attach_snapshot=settings.ALERT_ATTACH_SNAPSHOT)
            except ChannelError as exc:
                logger.error("%s in .env is invalid: %s", name, exc)
                continue
            channel = db.scalar(select(NotificationChannel).where(NotificationChannel.organization_id == org_id, NotificationChannel.name == name))
            if channel is None:
                channel = NotificationChannel(organization_id=org_id, kind=kind, name=name, min_severity=severity, config_secret="")
                db.add(channel)
            channel.min_severity = severity
            store_config(channel, config)
            channel.updated_at = utcnow()
            done.append(name)
    return done
