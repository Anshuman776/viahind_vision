"""
VIAHIND Vision - Authentication & authorization.

Sessions are signed JWTs carried in an httpOnly cookie, so that snapshot <img> requests and
WebSocket handshakes are authenticated without exposing the token to page scripts.
State-changing requests must also send the X-VV-CSRF header, which a cross-site form or
<img> cannot add.
"""

import hashlib
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Deque, Dict, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db import get_db, utcnow
from models.entities import Organization, User

CSRF_HEADER = "x-vv-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def validate_new_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status_code=422, detail="Password must be at least 10 characters.")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        raise HTTPException(status_code=422, detail="Password must mix upper- and lower-case letters and digits.")


def _credential_version(user: User) -> str:
    """Changes whenever the password changes, so a reset signs out existing sessions."""
    return hashlib.sha256(("session:" + user.password_hash).encode()).hexdigest()[:16]


def create_session_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "cv": _credential_version(user),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _user_from_token(token: Optional[str], db: Session) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    # A role change or deactivation takes effect immediately: the token's role must still match.
    if payload.get("role") != user.role or payload.get("cv") != _credential_version(user):
        return None
    org = db.get(Organization, user.organization_id)
    if org is None or not org.is_active:
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _user_from_token(request.cookies.get(settings.SESSION_COOKIE_NAME), db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF header.")
    return user


def require_viewer(user: User = Depends(get_current_user)) -> User:
    """Any signed-in role: dashboards, reports and aggregate figures."""
    return user


def require_operator(user: User = Depends(get_current_user)) -> User:
    """Monitoring, evidence, review and reconciliation (admins and operators, not viewers)."""
    if user.role not in ("admin", "operator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access required.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
    return user


def origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    """WebSocket origin check (prevents cross-site WebSocket hijacking).

    Allowed: configured CORS origins, or an origin whose hostname matches the host the
    browser connected to (the frontend and backend share a hostname on different ports).
    """
    if not origin:
        return False
    if origin in settings.CORS_ORIGINS:
        return True
    try:
        from urllib.parse import urlparse

        origin_host = urlparse(origin).hostname
        request_host = (host or "").rsplit(":", 1)[0].strip("[]")
        return bool(origin_host) and origin_host == request_host
    except ValueError:
        return False


def authenticate_websocket(websocket: WebSocket, db: Session) -> Optional[User]:
    if not origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
        return None
    return _user_from_token(websocket.cookies.get(settings.SESSION_COOKIE_NAME), db)


class LoginThrottle:
    """Rejects further attempts after repeated failures for a username or client address."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 300):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._prune(k, now)) >= self.max_failures for k in keys)

    def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._prune(k, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._failures.pop(k, None)


login_throttle = LoginThrottle()


def ensure_bootstrap_admin(db: Session) -> None:
    """Create the first administrator (in the default organization) from BOOTSTRAP_ADMIN_* when no users exist."""
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    username = settings.BOOTSTRAP_ADMIN_USERNAME.strip()
    password = settings.BOOTSTRAP_ADMIN_PASSWORD
    if not username or not password:
        return
    org_id = db.scalar(select(Organization.id).order_by(Organization.id).limit(1))
    if org_id is None:
        return
    db.add(User(organization_id=org_id, username=username, password_hash=hash_password(password), role="admin"))
    db.commit()
