import asyncio
import logging
from fastapi import WebSocket
from typing import Dict, List, Optional, Set

logger = logging.getLogger("viahind.ws")


class AlertConnectionManager:
    """WebSocket fan-out for the operator dashboard.

    - /ws/alerts: system channel (recorded events, camera status, occupancy changes, anomalies)
    - /ws/live/{camera_id}: live frames for one camera
    - /ws/stream/{camera_id}: frames pushed by a browser camera

    Camera workers run in threads; the *_threadsafe / publish_* methods hand work to the event loop.
    """

    def __init__(self):
        # System channel connections and the organization each signed-in user belongs to.
        # Messages are only ever sent to connections of the message's organization.
        self.active_alert_connections: Dict[WebSocket, int] = {}
        # Live camera viewers: camera_id -> set of WebSockets
        self.camera_viewers: Dict[str, Set[WebSocket]] = {}
        # Active browser/phone streamers: camera_id -> WebSocket
        self.phone_streamers: Dict[str, WebSocket] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._sending: Set[int] = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    # Alert channel methods
    async def connect_alerts(self, websocket: WebSocket, organization_id: int):
        await websocket.accept()
        self.active_alert_connections[websocket] = organization_id

    def disconnect_alerts(self, websocket: WebSocket):
        self.active_alert_connections.pop(websocket, None)

    async def broadcast_alert(self, message: dict, organization_id: int):
        for connection, org_id in list(self.active_alert_connections.items()):
            if org_id != organization_id:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect_alerts(connection)

    def broadcast_threadsafe(self, message: dict, organization_id: Optional[int]) -> None:
        if organization_id is None or self.loop is None or self.loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast_alert(message, organization_id), self.loop)

    # Browser stream ingestion methods
    async def register_streamer(self, camera_id: str, websocket: WebSocket):
        await websocket.accept()
        previous = self.phone_streamers.get(camera_id)
        self.phone_streamers[camera_id] = websocket
        if camera_id not in self.camera_viewers:
            self.camera_viewers[camera_id] = set()
        if previous is not None and previous is not websocket:
            # Only one device may feed a camera at a time; the newest connection wins.
            try:
                await previous.close(code=4009, reason="Another device started streaming this camera.")
            except Exception:
                pass

    def unregister_streamer(self, camera_id: str, websocket: Optional[WebSocket] = None):
        if camera_id in self.phone_streamers and (websocket is None or self.phone_streamers[camera_id] is websocket):
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

    def has_viewers(self, camera_id: str) -> bool:
        return bool(self.camera_viewers.get(camera_id))

    # Frame relay: camera worker -> viewers
    async def relay_frame(self, camera_id: str, frame_data: dict):
        if camera_id in self.camera_viewers:
            dead_sockets = set()
            for viewer in list(self.camera_viewers[camera_id]):
                key = id(viewer)
                if key in self._sending:
                    continue  # this viewer is still receiving the previous frame: skip, never queue
                self._sending.add(key)
                try:
                    await viewer.send_json(frame_data)
                except Exception:
                    dead_sockets.add(viewer)
                finally:
                    self._sending.discard(key)
            for dead in dead_sockets:
                self.unsubscribe_viewer(camera_id, dead)

    # Publisher interface used by vision.camera_worker
    def publish_frame(self, camera_id: str, payload: dict) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.relay_frame(camera_id, payload), self.loop)

    def publish_status(self, camera_id: str, status: dict) -> None:
        self.broadcast_threadsafe({"type": "camera_status", "camera_id": camera_id, "status": status}, status.get("organization_id"))


manager = AlertConnectionManager()
