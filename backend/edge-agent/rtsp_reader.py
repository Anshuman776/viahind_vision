"""
VIAHIND Vision Edge Agent - Video Stream Reader

Reads frames from RTSP / HTTP(MJPEG) cameras, local USB devices (integer index) or test
video files with OpenCV. Used by the backend camera workers (backend/vision/camera_worker.py).
The stream URL may contain credentials, so it is never logged or included in error messages.
"""
import os
import sys
import time
from typing import Optional, Union

# Keep FFmpeg quiet: its messages can include the stream URL (and therefore credentials).
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2  # noqa: E402

LIVE_PREFIXES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://", "tcp://")
OPEN_TIMEOUT_MS = 10000
READ_TIMEOUT_MS = 5000


class RTSPReader:
    def __init__(self, camera_id: str, stream_url: Union[str, int]):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.is_connected = False
        self._cap: Optional[cv2.VideoCapture] = None
        self.is_file = isinstance(stream_url, str) and not stream_url.lower().startswith(LIVE_PREFIXES)
        self.file_fps: float = 0.0

    def connect(self) -> bool:
        """Open the source. Returns False (without raising) if it cannot be opened."""
        self.release()
        source = self.stream_url
        cap = None
        if isinstance(source, int) and sys.platform.startswith("win"):
            # DirectShow opens most Windows webcams faster than the default backend.
            cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = None
        if cap is None and isinstance(source, str) and source.lower().startswith(LIVE_PREFIXES):
            # Bounded open/read times: a dead network camera must fail fast so the worker can
            # report it and reconnect, instead of blocking inside FFmpeg indefinitely.
            cap = cv2.VideoCapture(
                source,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS],
            )
            if not cap.isOpened():
                cap.release()
                cap = None
                return False
        if cap is None:
            cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            cap.release()
            return False
        if not self.is_file:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low on live streams
        else:
            self.file_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self._cap = cap
        self.is_connected = True
        return True

    def read_frame(self):
        """Return the next BGR frame, or None if no frame could be read."""
        if not self.is_connected or self._cap is None:
            raise ConnectionError(f"Stream {self.camera_id} is not connected.")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return frame

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.is_connected = False


def wait_for_file_frame(started: float, index: int, fps: float) -> None:
    """Pace playback of a test clip at its native frame rate."""
    if fps <= 0:
        return
    delay = started + index / fps - time.monotonic()
    if delay > 0:
        time.sleep(delay)
