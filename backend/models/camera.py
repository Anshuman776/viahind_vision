from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class PhoneCameraRegisterRequest(BaseModel):
    id: str = Field(..., description="Unique camera ID, e.g., CAM-PHONE-01")
    name: str = Field(..., description="Display name, e.g. Phone Camera 1")
    floor: str = Field(default="Floor 1", description="Assigned floor in PG")
    location: str = Field(default="Corridor / Room", description="Assigned room or location")
    stream_type: Literal["browser_stream", "ip_webcam_mjpeg", "rtsp"] = "browser_stream"
    ip_stream_url: Optional[str] = Field(None, description="Direct URL from IP Webcam app, e.g. http://192.168.1.15:8080/video")

class CameraStatusModel(BaseModel):
    id: str
    name: str
    floor: str
    location: str
    status: Literal["online", "degraded", "offline"] = "online"
    fps: int = 30
    stream_type: str = "rtsp"
    is_phone_camera: bool = False
    stream_url: Optional[str] = None
    last_frame_timestamp: Optional[str] = None
    has_active_alert: bool = False
    live_frame_base64: Optional[str] = None
