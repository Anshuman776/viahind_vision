"""
VIAHIND Vision Edge Agent - RTSP Video Stream Reader
"""
import time
from typing import Optional

class RTSPReader:
    def __init__(self, camera_id: str, stream_url: str):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.is_connected = False

    def connect(self) -> bool:
        """Connect to camera RTSP endpoint"""
        self.is_connected = True
        return True

    def read_frame(self):
        """Yield video frame buffer"""
        if not self.is_connected:
            raise ConnectionError(f"RTSP stream {self.camera_id} is not connected.")
        return None

    def release(self):
        self.is_connected = False
