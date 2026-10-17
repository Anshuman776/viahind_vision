from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import create_session_token, get_current_user, hash_password, login_throttle, verify_password
from config import settings
from db import get_db, utcnow
from models.entities import Organization, User
from models.schemas import LoginRequest
from services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Equalises timing between unknown usernames and wrong passwords.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "organization_id": user.organization_id,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "unknown"
    keys = (f"user:{body.username.lower()}", f"ip:{client}")
    if login_throttle.is_blocked(*keys):
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Try again in a few minutes.")

    user = db.scalar(select(User).where(User.username == body.username))
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid or not user.is_active:
        login_throttle.record_failure(*keys)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    login_throttle.reset(*keys)
    user.last_login_at = utcnow()
    record_audit(db, user, "auth.login", "user", user.id, {"ip": client})
    db.commit()
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        create_session_token(user),
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return serialize_user(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"status": "signed_out"}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = serialize_user(user)
    org = db.get(Organization, user.organization_id)
    data["organization"] = {"id": org.id, "name": org.name, "plan": org.plan, "max_cameras": org.max_cameras}
    return data


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    """Lets the sign-in page explain how to create the first account."""
    return {"has_users": db.scalar(select(User.id).limit(1)) is not None}
