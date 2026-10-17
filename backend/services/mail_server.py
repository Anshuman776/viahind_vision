"""
Outgoing mail server (SMTP) per organization, managed from Settings → Notifications.

The configuration (host, port, security, sender, username, password) is encrypted at rest with
the per-purpose key from services/secretbox.py. The password is never returned by the API.
When an organization has no stored configuration, the SMTP_* settings from the environment are
used, so existing .env-based installs keep working.
"""

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import List, Optional

from sqlalchemy.orm import Session

from config import settings
from db import session_scope
from services.secretbox import SecretError, decrypt_json, encrypt_json

PURPOSE = "mail-server"
HOST = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,}$")
SECURITY = ("starttls", "ssl", "none")

# Common providers, offered as presets in the console.
PRESETS = {
    "gmail": {"host": "smtp.gmail.com", "port": 587, "security": "starttls",
              "hint": "Use a Google App Password (Google account → Security → 2-Step Verification → App passwords), not your normal password."},
    "outlook": {"host": "smtp.office365.com", "port": 587, "security": "starttls", "hint": "Use the full mailbox address as the username."},
    "zoho": {"host": "smtp.zoho.in", "port": 465, "security": "ssl", "hint": "Use smtp.zoho.com outside India."},
    "custom": {"host": "", "port": 587, "security": "starttls", "hint": ""},
}


class MailError(ValueError):
    pass


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    security: str
    username: str
    password: str
    from_address: str
    from_name: str
    source: str  # "console" | "environment"

    @property
    def sender(self) -> str:
        return formataddr((self.from_name, self.from_address)) if self.from_name else self.from_address


def _env_config() -> Optional[MailConfig]:
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        return None
    name, address = parseaddr(settings.SMTP_FROM)
    return MailConfig(settings.SMTP_HOST, settings.SMTP_PORT, "starttls" if settings.SMTP_STARTTLS else ("ssl" if settings.SMTP_PORT == 465 else "none"),
                      settings.SMTP_USERNAME, settings.SMTP_PASSWORD, address or settings.SMTP_FROM, name, "environment")


def stored_config(db: Session, organization_id: int) -> Optional[MailConfig]:
    from services.site_settings import get_site_settings

    row = get_site_settings(db, organization_id)
    if not row.mail_config_secret:
        return None
    data = decrypt_json(PURPOSE, row.mail_config_secret)
    return MailConfig(data["host"], int(data["port"]), data["security"], data.get("username", ""), data.get("password", ""),
                      data["from_address"], data.get("from_name", ""), "console")


def effective_config(organization_id: Optional[int]) -> Optional[MailConfig]:
    """The organization's console configuration, else the environment's, else None."""
    if organization_id is not None:
        with session_scope() as db:
            try:
                cfg = stored_config(db, organization_id)
            except SecretError:
                cfg = None
        if cfg is not None:
            return cfg
    return _env_config()


def is_configured(db: Session, organization_id: int) -> bool:
    try:
        return stored_config(db, organization_id) is not None or _env_config() is not None
    except SecretError:
        return _env_config() is not None


def save_config(db: Session, organization_id: int, host: str, port: int, security: str, username: str,
                password: Optional[str], from_address: str, from_name: str) -> None:
    """Validate and store. A None password keeps the stored one. Caller commits."""
    from services.site_settings import get_site_settings

    host = host.strip()
    if not HOST.match(host) or "." not in host:
        raise MailError("Enter the mail server host name, e.g. smtp.gmail.com.")
    if not 1 <= int(port) <= 65535:
        raise MailError("The port must be between 1 and 65535 (usually 587 or 465).")
    if security not in SECURITY:
        raise MailError("Security must be STARTTLS, SSL/TLS or none.")
    if settings.IS_PRODUCTION and security == "none":
        raise MailError("Unencrypted SMTP is not allowed in production; choose STARTTLS or SSL/TLS.")
    from_address = from_address.strip()
    if not EMAIL.match(from_address):
        raise MailError("Enter a valid sender address.")
    from_name = from_name.strip()[:80]
    if any(c in from_name for c in "\r\n<>\""):
        raise MailError("The sender name cannot contain line breaks, quotes or angle brackets.")
    username = username.strip()[:254]
    row = get_site_settings(db, organization_id)
    if password is None:
        try:
            current = stored_config(db, organization_id)
        except SecretError:
            current = None
        password = current.password if current is not None and current.source == "console" else ""
    if len(password) > 512:
        raise MailError("The password is too long.")
    row.mail_config_secret = encrypt_json(PURPOSE, {
        "host": host, "port": int(port), "security": security, "username": username, "password": password,
        "from_address": from_address, "from_name": from_name,
    })


def clear_config(db: Session, organization_id: int) -> None:
    from services.site_settings import get_site_settings

    get_site_settings(db, organization_id).mail_config_secret = None


def serialize(db: Session, organization_id: int) -> dict:
    try:
        cfg = stored_config(db, organization_id)
        error = None
    except SecretError as exc:
        cfg, error = None, str(exc)
    env = _env_config()
    shown = cfg or env
    return {
        "configured": shown is not None,
        "source": shown.source if shown else None,
        "host": shown.host if shown else "",
        "port": shown.port if shown else 587,
        "security": shown.security if shown else "starttls",
        "username": shown.username if shown else "",
        "has_password": bool(shown and shown.password),
        "from_address": shown.from_address if shown else "",
        "from_name": shown.from_name if shown else "",
        "error": error,
        "presets": PRESETS,
    }


def send(cfg: MailConfig, recipients: List[str], subject: str, body: str, image: Optional[bytes] = None,
         html: Optional[str] = None) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")[:200]
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    if image:
        msg.add_attachment(image, maintype="image", subtype="jpeg", filename="evidence.jpg")
    context = ssl.create_default_context()
    try:
        if cfg.security == "ssl":
            smtp = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20, context=context)
        else:
            smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
        with smtp:
            if cfg.security == "starttls":
                smtp.starttls(context=context)
            if cfg.username:
                smtp.login(cfg.username, cfg.password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server rejected the username or password. For Gmail use an App Password.") from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError("The mail server refused the recipient address(es).") from None
    except smtplib.SMTPException as exc:
        raise MailError(f"The mail server reported an error ({type(exc).__name__}).") from None
    except (OSError, ssl.SSLError) as exc:
        raise MailError(f"Could not connect to {cfg.host}:{cfg.port} ({type(exc).__name__}). Check host, port and security.") from None
