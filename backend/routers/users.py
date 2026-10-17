from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import hash_password, require_admin, validate_new_password
from services.tenancy import get_owned
from db import get_db
from models.entities import User
from models.schemas import UserCreate, UserUpdate
from routers.auth import serialize_user
from services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return [serialize_user(u) for u in db.scalars(select(User).where(User.organization_id == admin.organization_id).order_by(User.username))]


@router.post("", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    validate_new_password(body.password)
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(status_code=409, detail="That username is already in use.")
    user = User(organization_id=admin.organization_id, username=body.username, email=body.email or None,
                password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.flush()
    record_audit(db, admin, "user.create", "user", user.id, {"username": user.username, "role": user.role})
    db.commit()
    return serialize_user(user)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = get_owned(db, User, user_id, admin, "User not found.")
    changes = {}
    demoting = body.role == "operator" and user.role == "admin"
    deactivating = body.is_active is False and user.is_active
    if (demoting or deactivating) and user.role == "admin":
        active_admins = db.scalar(select(func.count()).select_from(User).where(
            User.organization_id == admin.organization_id, User.role == "admin", User.is_active.is_(True)))
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="At least one active administrator is required.")
    if body.role is not None and body.role != user.role:
        changes["role"] = [user.role, body.role]
        user.role = body.role
    if body.email is not None and (body.email or None) != user.email:
        changes["email"] = "changed"
        user.email = body.email or None
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = [user.is_active, body.is_active]
        user.is_active = body.is_active
    if body.password:
        validate_new_password(body.password)
        user.password_hash = hash_password(body.password)
        changes["password"] = "reset"
    if changes:
        record_audit(db, admin, "user.update", "user", user.id, changes)
    db.commit()
    return serialize_user(user)
