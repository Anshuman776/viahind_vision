"""Hybrid sync: edge status (edge mode), node registry and idempotent event ingest (cloud mode)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin
from config import settings
from db import get_db
from models.entities import SyncNode, User
from models.schemas import SyncNodeCreate
from services.audit import record_audit
from services.sync import authenticate_node, hash_token, ingest_events, new_token, outbox_status, serialize_node
from services.tenancy import get_owned, owned_location

router = APIRouter(prefix="/sync", tags=["sync"])

MAX_BATCH = 500


class IngestBody(BaseModel):
    node_id: str = Field(max_length=48)
    events: List[dict] = Field(max_length=MAX_BATCH)


@router.get("/status")
def sync_status(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    data = outbox_status(db, admin.organization_id)
    if settings.IS_CLOUD:
        data["nodes"] = [serialize_node(n) for n in db.scalars(select(SyncNode).where(SyncNode.organization_id == admin.organization_id))]
    return data


def _cloud_only():
    if not settings.IS_CLOUD:
        raise HTTPException(status_code=404, detail="This server is not running in cloud mode.")


@router.post("/nodes", status_code=201)
def create_node(body: SyncNodeCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _cloud_only()
    owned_location(db, admin, body.location_id)
    if db.get(SyncNode, body.id) is not None:
        raise HTTPException(status_code=409, detail="This node ID is not available.")
    token = new_token()
    node = SyncNode(id=body.id, organization_id=admin.organization_id, location_id=body.location_id, name=body.name.strip(),
                    token_hash=hash_token(token))
    db.add(node)
    record_audit(db, admin, "sync_node.create", "sync_node", node.id, {"location_id": node.location_id})
    db.commit()
    # The token is shown once; only its hash is stored.
    return {**serialize_node(node), "token": token}


@router.delete("/nodes/{node_id}", status_code=204)
def disable_node(node_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _cloud_only()
    node = get_owned(db, SyncNode, node_id, admin, "Node not found.")
    node.enabled = False
    record_audit(db, admin, "sync_node.disable", "sync_node", node.id, {})
    db.commit()
    return Response(status_code=204)


@router.post("/events")
def ingest(body: IngestBody, request: Request, db: Session = Depends(get_db)):
    """Called by edge nodes with `Authorization: Bearer <node token>`. Idempotent."""
    _cloud_only()
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    node = authenticate_node(db, token)
    if node is None or node.id != body.node_id:
        raise HTTPException(status_code=401, detail="Unknown or disabled node.")
    result = ingest_events(db, node, body.events)
    db.commit()
    return result
