import json
import asyncio
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Set

class AlertConnectionManager:
    def __init__(self):
        # General alerts WebSocket connections
        self.active_alert_connections: List[WebSocket] = []
        # Live camera viewers: camera_id -> set of WebSockets
        self.camera_viewers: Dict[str, Set[WebSocket]] = {}
        # Active phone streamers: camera_id -> WebSocket
        self.phone_streamers: Dict[str, WebSocket] = {}

    # Alert channel methods
    async def connect_alerts(self, websocket: WebSocket):
        await websocket.accept()
        self.active_alert_connections.append(websocket)

    def disconnect_alerts(self, websocket: WebSocket):
        if websocket in self.active_alert_connections:
            self.active_alert_connections.remove(websocket)

    async def broadcast_alert(self, message: dict):
        for connection in list(self.active_alert_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect_alerts(connection)

    # Phone stream ingestion methods
    async def register_streamer(self, camera_id: str, websocket: WebSocket):
        await websocket.accept()
        self.phone_streamers[camera_id] = websocket
        if camera_id not in self.camera_viewers:
            self.camera_viewers[camera_id] = set()

    def unregister_streamer(self, camera_id: str):
        if camera_id in self.phone_streamers:
            del self.phone_streamers[camera_id]

    # Dashboard viewer subscription methods
    async def subscribe_viewer(self, camera_id: str, websocket: WebSocket):
        await websocket.accept()
        if camera_id not in self.camera_viewers:
            self.camera_viewers[camera_id] = set()
        self.camera_viewers[camera_id].add(websocket)

    def unsubscribe_viewer(self, camera_id: str, websocket: WebSocket):
        if camera_id in self.camera_viewers and websocket in self.camera_viewers[camera_id]:
            self.camera_viewers[camera_id].remove(websocket)

    # Frame relay: Streamer -> Viewers
    async def relay_frame(self, camera_id: str, frame_data: dict):
        if camera_id in self.camera_viewers:
            dead_sockets = set()
            for viewer in self.camera_viewers[camera_id]:
                try:
                    await viewer.send_json(frame_data)
                except Exception:
                    dead_sockets.add(viewer)
            for dead in dead_sockets:
                self.unsubscribe_viewer(camera_id, dead)

manager = AlertConnectionManager()
