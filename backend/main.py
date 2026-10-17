import asyncio
import base64
import json
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Deque, Dict

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from auth import authenticate_websocket, ensure_bootstrap_admin
from config import BASE_DIR, settings
from db import SessionLocal
from models.entities import Camera
from routers import (
    alert_config, alerts, anomaly, auth as auth_router, cameras, events, locations, ml, overview, reports, site, sync, users, visits,
)
from runtime import runtime
from services import alerts as alert_service
from services.alert_engine import AlertEngine, on_event_recorded, on_video_anomaly, on_zone_event
from services.anomaly_store import store_anomaly
from services.events import EventRecorder
from services.evidence import evidence_policy
from services.notifications import NotificationDispatcher, ensure_env_channels
from services.occupancy import compute_occupancy
from services.retention import RetentionScheduler
from services.snapshots import storage_status
from vision.anomaly import AnomalyDetectorAdapter
from vision.camera_manager import CameraManager
from vision.detector import detector_availability
from websocket import manager

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("viahind")

APP_VERSION = "3.0.0"


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.upgrade(cfg, "head")


def _on_event_recorded(event: dict) -> None:
    org_id = event.get("organization_id")
    with SessionLocal() as db:
        occupancy = compute_occupancy(db, org_id)
    manager.broadcast_threadsafe({"type": "event_recorded", "event": event, "occupancy": occupancy}, org_id)
    on_event_recorded(event)


def _on_anomaly(result) -> None:
    stored = store_anomaly(result)
    if stored:
        manager.broadcast_threadsafe({"type": "anomaly", "anomaly": stored}, stored["organization_id"])
        on_video_anomaly(stored, result.snapshot_jpeg)


def _on_alert_changed(organization_id: int, alert: dict, created: bool) -> None:
    manager.broadcast_threadsafe({"type": "alert" if created else "alert_updated", "alert": alert}, organization_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_startup()
    run_migrations()
    with SessionLocal() as db:
        ensure_bootstrap_admin(db)
    manager.bind_loop(asyncio.get_running_loop())
    alert_service.on_alert_changed = _on_alert_changed

    runtime.recorder = EventRecorder(on_recorded=_on_event_recorded)
    runtime.recorder.start_retry_loop()
    runtime.anomaly = AnomalyDetectorAdapter(on_event=_on_anomaly)
    runtime.anomaly.initialize_anomaly_detector()
    runtime.cameras = CameraManager(
        runtime.recorder, publisher=manager, anomaly=runtime.anomaly,
        zone_sink=on_zone_event, evidence_policy=evidence_policy,
    )
    runtime.cameras.refresh_params()
    runtime.cameras.resume_on_startup()
    runtime.retention = RetentionScheduler()
    runtime.retention.start()
    for name in ensure_env_channels():
        logger.info("Notification channel configured from .env: %s", name)
    runtime.notifications = NotificationDispatcher()
    runtime.notifications.start()
    runtime.alert_engine = AlertEngine(workers=runtime.cameras.workers, pending_events=runtime.recorder.pending_by_organization)
    runtime.alert_engine.start()
    if settings.IS_EDGE:
        from services.sync import SyncPusher

        runtime.sync = SyncPusher()
        runtime.sync.start()
    logger.info("VIAHIND Vision %s started (%s, %s mode)", APP_VERSION, settings.APP_ENV, settings.DEPLOYMENT_MODE)
    try:
        yield
    finally:
        runtime.cameras.shutdown()
        runtime.anomaly.shutdown()
        runtime.recorder.stop()
        runtime.retention.stop()
        runtime.notifications.stop()
        runtime.alert_engine.stop()
        if runtime.sync:
            runtime.sync.stop()


app = FastAPI(
    title=settings.APP_NAME,
    version=APP_VERSION,
    description="VIAHIND Vision: AI-powered CCTV business intelligence - footfall, occupancy, reviewable alerts and reports.",
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url=None if settings.IS_PRODUCTION else "/docs",
    redoc_url=None,
    openapi_url=None if settings.IS_PRODUCTION else "/openapi.json",
)

# The frontend reaches the API through same-origin Next.js rewrites; CORS is only needed for
# the explicitly configured origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-VV-CSRF"],
)


class RateLimiter:
    """Sliding one-minute window per client address (in-process; put a proxy limit in front for
    multi-instance deployments). Expensive endpoints cost more."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, cost: int = 1) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) + cost > self.per_minute:
                return False
            q.extend([now] * cost)
            if len(self._hits) > 10000:  # bound memory under address churn
                for k in [k for k, v in self._hits.items() if not v][:5000]:
                    del self._hits[k]
            return True


rate_limiter = RateLimiter(settings.RATE_LIMIT_PER_MINUTE)
EXPENSIVE = ("/export.csv", "/reports/summary", "/train", "/test")


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    path = request.url.path
    if path.startswith(settings.API_V1_PREFIX) and settings.RATE_LIMIT_PER_MINUTE > 0:
        client = request.client.host if request.client else "unknown"
        cost = 10 if path.endswith(EXPENSIVE) else 1
        if not rate_limiter.allow(client, cost):
            return JSONResponse(status_code=429, content={"detail": "Too many requests. Slow down and try again shortly."},
                                headers={"Retry-After": "30"})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.COOKIE_SECURE:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if path.startswith(settings.API_V1_PREFIX):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


for r in (auth_router, users, cameras, events, visits, overview, site, anomaly, alerts, locations, alert_config, reports, ml, sync):
    app.include_router(r.router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """Liveness: the process is up."""
    return {"status": "ok", "service": settings.APP_NAME, "version": APP_VERSION, "demo_mode": settings.IS_DEMO}


@app.get("/health/ready")
def readiness():
    """Readiness: database reachable, storage available, workers and models status."""
    checks = {}
    ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except SQLAlchemyError as exc:
        ok = False
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    storage = storage_status()
    checks["storage"] = {"ok": not storage["low"], **storage}
    available, reason = detector_availability()
    checks["person_detector"] = {"ok": available, "message": reason}
    checks["video_anomaly"] = {k: v for k, v in (runtime.anomaly.health_check() if runtime.anomaly else {"enabled": False}).items()
                               if k in ("enabled", "status", "mode")}
    checks["events"] = {
        "pending_writes": runtime.recorder.pending_count() if runtime.recorder else 0,
        "last_db_error": runtime.recorder.last_db_error if runtime.recorder else None,
    }
    checks["cameras"] = {"live": runtime.cameras.running_count() if runtime.cameras else 0}
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "checks": checks})


async def _authorize(websocket: WebSocket):
    with SessionLocal() as db:
        user = authenticate_websocket(websocket, db)
    if user is None:
        await websocket.close(code=1008)
    return user


# 1. System channel: recorded events, camera status, occupancy and alerts (organization-scoped)
@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    user = await _authorize(websocket)
    if user is None:
        return
    await manager.connect_alerts(websocket, user.organization_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_alerts(websocket)
    except Exception:
        manager.disconnect_alerts(websocket)


def _decode_frame_message(message: dict):
    """Binary JPEG frames, or the legacy JSON {"image": "data:image/jpeg;base64,..."} format."""
    if message.get("bytes") is not None:
        return message["bytes"]
    raw = message.get("text")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        image = payload.get("image") if isinstance(payload, dict) else None
        if not isinstance(image, str):
            return None
        return base64.b64decode(image.split(",", 1)[-1], validate=True)
    except (ValueError, json.JSONDecodeError):
        return None


def _camera_for(user, camera_id: str):
    with SessionLocal() as db:
        cam = db.get(Camera, camera_id)
        if cam is None or cam.organization_id != user.organization_id:
            return None
        return cam


# 2. Ingestion: a signed-in operator's browser (laptop webcam or phone) streams frames to a browser camera
@app.websocket("/ws/stream/{camera_id}")
async def phone_camera_stream_endpoint(websocket: WebSocket, camera_id: str):
    user = await _authorize(websocket)
    if user is None:
        return
    if user.role not in ("admin", "operator"):
        await websocket.close(code=1008)
        return
    cam = _camera_for(user, camera_id)
    worker = runtime.cameras.worker(camera_id) if runtime.cameras else None
    if cam is None or cam.source_type != "browser" or worker is None:
        await websocket.close(code=4404, reason="Start this browser camera from Live Camera first.")
        return
    await manager.register_streamer(camera_id, websocket)
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            frame = _decode_frame_message(message)
            if frame is None:
                continue
            if len(frame) > settings.MAX_INGEST_FRAME_BYTES:
                await websocket.close(code=1009, reason="Frame too large.")
                break
            if not runtime.cameras.push_frame(camera_id, frame):
                await websocket.close(code=4404, reason="The camera was stopped.")
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister_streamer(camera_id, websocket)


# 3. Viewer: dashboard receives live frames (with tracking overlay data) for one camera
@app.websocket("/ws/live/{camera_id}")
async def camera_viewer_endpoint(websocket: WebSocket, camera_id: str):
    user = await _authorize(websocket)
    if user is None:
        return
    if user.role not in ("admin", "operator") or _camera_for(user, camera_id) is None:
        await websocket.close(code=1008)
        return
    await manager.subscribe_viewer(camera_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        manager.unsubscribe_viewer(camera_id, websocket)
