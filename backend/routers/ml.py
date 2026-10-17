"""Event-level anomaly model: status, training (admins) and a dry-run score of recent hours."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from auth import require_admin
from config import settings
from db import get_db
from models.entities import User
from models.schemas import TrainRequest
from services.audit import record_audit
from services.ml_anomaly import model_status, train_model

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/anomaly-model")
def status(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return model_status(db, admin.organization_id)


@router.post("/anomaly-model/train")
async def train(body: TrainRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if not settings.ML_ANOMALY_ENABLED:
        raise HTTPException(status_code=409, detail="ML anomaly detection is disabled on this server (ML_ANOMALY_ENABLED=False).")
    try:
        result = await run_in_threadpool(train_model, admin.organization_id, admin.username, body.days, body.contamination)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    record_audit(db, admin, "ml.train", "anomaly_model", result["id"], {"status": result["status"], "version": result["version"]})
    db.commit()
    return result
