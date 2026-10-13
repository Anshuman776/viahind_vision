import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from auth import authenticate_websocket, ensure_bootstrap_admin
from config import BASE_DIR, settings
from db import SessionLocal
from models.entities import Camera
from routers import alerts, anomaly, auth as auth_router, cameras, events, overview, site, users, visits
from runtime import runtime
from services.anomaly_store import store_anomaly
from services.events import EventRecorder
from services.occupancy import compute_occupancy
from services.retention import RetentionScheduler
from services.snapshots import storage_status
from vision.anomaly import AnomalyDetectorAdapter
from vision.camera_manager import CameraManager
from vision.detector import detector_availability
from websocket import manager

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("viahind")


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.upgrade(cfg, "head")


def _on_event_recorded(event: dict) -> None:
    with SessionLocal() as db:
        occupancy = compute_occupancy(db)
    manager.broadcast_threadsafe({"type": "event_recorded", "event": event, "occupancy": occupancy})


def _on_anomaly(result) -> None:
    manager.broadcast_threadsafe({"type": "anomaly", "anomaly": store_anomaly(result)})


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_startup()
    run_migrations()
    with SessionLocal() as db:
        ensure_bootstrap_admin(db)
    manager.bind_loop(asyncio.get_running_loop())

    runtime.recorder = EventRecorder(on_recorded=_on_event_recorded)
    runtime.recorder.start_retry_loop()
    runtime.anomaly = AnomalyDetectorAdapter(on_event=_on_anomaly)
    runtime.anomaly.initialize_anomaly_detector()
    runtime.cameras = CameraManager(runtime.recorder, publisher=manager, anomaly=runtime.anomaly)
    runtime.cameras.refresh_params()
    runtime.cameras.resume_on_startup()
    runtime.retention = RetentionScheduler()
    runtime.retention.start()
    logger.info("VIAHIND Vision started (%s)", settings.APP_ENV)
    try:
        yield
    finally:
        runtime.cameras.shutdown()
        runtime.anomaly.shutdown()
        runtime.recorder.stop()
        runtime.retention.stop()


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Backend API for VIAHIND Vision - PG entrance surveillance: cameras, entry/exit events, visits and occupancy.",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# The frontend reaches the API through same-origin Next.js rewrites; CORS is only needed for
# the explicitly configured origins. (The previous "any origin with credentials" rule is gone.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-VV-CSRF"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


for r in (auth_router, users, cameras, events, visits, overview, site, anomaly, alerts):
    app.include_router(r.router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """Liveness: the process is up."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "demo_mode": settings.IS_DEMO,
        "model_version": settings.FIGHT_DETECTOR_VERSION,
        "phone_streaming_supported": True,
    }


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
    checks["anomaly"] = runtime.anomaly.health_check() if runtime.anomaly else {"enabled": False}
    checks["events"] = {
        "pending_writes": runtime.recorder.pending_count() if runtime.recorder else 0,
        "last_db_error": runtime.recorder.last_db_error if runtime.recorder else None,
    }
    checks["cameras"] = {"live": runtime.cameras.running_count() if runtime.cameras else 0}
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "demo_mode": settings.IS_DEMO, "checks": checks})


async def _authorize(websocket: WebSocket):
    with SessionLocal() as db:
        user = authenticate_websocket(websocket, db)
    if user is None:
        await websocket.close(code=1008)
    return user


# 1. System channel: recorded events, camera status, occupancy and anomaly notifications
@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    if await _authorize(websocket) is None:
        return
    await manager.connect_alerts(websocket)
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


# 2. Ingestion: a signed-in operator's browser (laptop webcam or phone) streams frames to a browser camera
@app.websocket("/ws/stream/{camera_id}")
async def phone_camera_stream_endpoint(websocket: WebSocket, camera_id: str):
    user = await _authorize(websocket)
    if user is None:
        return
    with SessionLocal() as db:
        cam = db.get(Camera, camera_id)
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
    if await _authorize(websocket) is None:
        return
    await manager.subscribe_viewer(camera_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        manager.unsubscribe_viewer(camera_id, websocket)
