import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
try:
    from .config import settings
    from .routers import alerts, cameras
    from .websocket import manager
except ImportError:
    from config import settings
    from routers import alerts, cameras
    from websocket import manager

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Backend API and WebSocket stream broker for multi-floor PG CCTV security monitoring with smartphone camera ingestion.",
    debug=settings.DEBUG,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(alerts.router, prefix=settings.API_V1_PREFIX)
app.include_router(cameras.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "facility": settings.ACTIVE_FACILITY_NAME,
        "model_version": settings.FIGHT_DETECTOR_VERSION,
        "phone_streaming_supported": True,
    }

# 1. System Alerts WebSocket channel
@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    await manager.connect_alerts(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_alerts(websocket)
    except Exception:
        manager.disconnect_alerts(websocket)

# 2. Ingestion WebSocket: Smartphone streams live video frames to backend
@app.websocket("/ws/stream/{camera_id}")
async def phone_camera_stream_endpoint(websocket: WebSocket, camera_id: str):
    await manager.register_streamer(camera_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            frame_payload = json.loads(data)
            frame_payload["timestamp"] = datetime.utcnow().isoformat()
            frame_payload["camera_id"] = camera_id
            
            # Cache latest frame for snapshot preview
            cameras.LATEST_PHONE_FRAMES[camera_id] = frame_payload.get("image")
            
            # Relay live frame to all active viewers subscribed to this camera
            await manager.relay_frame(camera_id, frame_payload)
            
            # If phone streamer flagged simulated altercation, broadcast alert
            if frame_payload.get("trigger_alert"):
                await manager.broadcast_alert({
                    "event": "INCIDENT_DETECTED",
                    "camera_id": camera_id,
                    "event_type": "Physical Altercation",
                    "severity": "critical",
                    "confidence_score": 0.942,
                    "timestamp": frame_payload["timestamp"]
                })
    except (WebSocketDisconnect, Exception):
        manager.unregister_streamer(camera_id)

# 3. Viewer WebSocket: Dashboard views live stream relayed from phone
@app.websocket("/ws/live/{camera_id}")
async def camera_viewer_endpoint(websocket: WebSocket, camera_id: str):
    await manager.subscribe_viewer(camera_id, websocket)
    try:
        # Immediately push cached latest frame if available so tile displays feed instantly
        if camera_id in cameras.LATEST_PHONE_FRAMES and cameras.LATEST_PHONE_FRAMES[camera_id]:
            await websocket.send_json({
                "image": cameras.LATEST_PHONE_FRAMES[camera_id],
                "camera_id": camera_id,
                "cached": True
            })
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        manager.unsubscribe_viewer(camera_id, websocket)
