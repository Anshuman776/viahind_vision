from fastapi import APIRouter, HTTPException, Response
from typing import List
from datetime import datetime
try:
    from ..models.camera import CameraStatusModel, PhoneCameraRegisterRequest
except ImportError:
    from models.camera import CameraStatusModel, PhoneCameraRegisterRequest

router = APIRouter(prefix="/cameras", tags=["cameras"])

# In-memory storage of connected cameras (defaults + phone cameras)
CONNECTED_CAMERAS: List[CameraStatusModel] = [
    CameraStatusModel(
        id="CAM-G-LOBBY-01",
        name="Ground Reception Turnstile",
        floor="Ground Floor",
        location="Main Security Turnstile & Lobby",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=True,
    ),
    CameraStatusModel(
        id="CAM-G-DINING-02",
        name="Ground Mess & Dining Hall",
        floor="Ground Floor",
        location="Resident Dining Facility",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
    ),
    CameraStatusModel(
        id="CAM-F1-CORR-04",
        name="Floor 1 Main Corridor East",
        floor="Floor 1",
        location="Boys Wing Corridor near Room 112",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=True,
    ),
    CameraStatusModel(
        id="CAM-F2-STAIR-02",
        name="Floor 2 Emergency Fire Stair",
        floor="Floor 2",
        location="Emergency Fire Stairwell B",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=True,
    ),
    CameraStatusModel(
        id="CAM-F3-STUDY-01",
        name="Floor 3 Common Study Lounge",
        floor="Floor 3",
        location="Central Reading & Work Hall",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=True,
    ),
    CameraStatusModel(
        id="CAM-F1-PHONE-01",
        name="Floor 1 Phone Cam - East",
        floor="Floor 1",
        location="Boys Wing Corridor East",
        status="online",
        fps=30,
        stream_type="browser_stream",
        is_phone_camera=True,
        stream_url="/ws/live/CAM-F1-PHONE-01",
        has_active_alert=False,
    ),
    CameraStatusModel(
        id="CAM-ROOF-PERIM-01",
        name="Rooftop Terrace North Perimeter",
        floor="Rooftop",
        location="Water Tank & Solar Panel Terrace",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=True,
    ),
]

# Latest frame cache for phone camera feeds: camera_id -> base64/bytes
LATEST_PHONE_FRAMES = {}

@router.get("", response_model=List[CameraStatusModel])
async def list_cameras():
    """
    Returns all registered cameras including live connected smartphones.
    """
    for cam in CONNECTED_CAMERAS:
        if cam.id in LATEST_PHONE_FRAMES:
            cam.live_frame_base64 = LATEST_PHONE_FRAMES[cam.id]
    return CONNECTED_CAMERAS

@router.get("/{camera_id}/frame")
async def get_camera_frame(camera_id: str):
    """
    Retrieve latest image frame snapshot from a smartphone stream.
    """
    if camera_id in LATEST_PHONE_FRAMES and LATEST_PHONE_FRAMES[camera_id]:
        return {"camera_id": camera_id, "image": LATEST_PHONE_FRAMES[camera_id]}
    raise HTTPException(status_code=404, detail="No frame cached for this camera")

@router.post("/phone", response_model=CameraStatusModel)
async def register_phone_camera(req: PhoneCameraRegisterRequest):
    """
    Register a smartphone camera as an active CCTV stream in VIAHIND Vision.
    """
    # Check if already registered, update if so
    for cam in CONNECTED_CAMERAS:
        if cam.id == req.id:
            cam.name = req.name
            cam.floor = req.floor
            cam.location = req.location
            cam.stream_type = req.stream_type
            cam.stream_url = req.ip_stream_url
            cam.status = "online"
            cam.last_frame_timestamp = datetime.utcnow().isoformat()
            return cam

    # Register as new camera
    new_cam = CameraStatusModel(
        id=req.id,
        name=req.name,
        floor=req.floor,
        location=req.location,
        status="online",
        fps=30,
        stream_type=req.stream_type,
        is_phone_camera=True,
        stream_url=req.ip_stream_url or f"/ws/live/{req.id}",
        last_frame_timestamp=datetime.utcnow().isoformat(),
        has_active_alert=False,
    )
    # Put phone camera at the top of the list for high visibility
    CONNECTED_CAMERAS.insert(0, new_cam)
    return new_cam

@router.delete("/phone/{camera_id}")
async def disconnect_phone_camera(camera_id: str):
    """
    Disconnect a smartphone camera stream.
    """
    global CONNECTED_CAMERAS
    initial_len = len(CONNECTED_CAMERAS)
    CONNECTED_CAMERAS = [c for c in CONNECTED_CAMERAS if not (c.id == camera_id and c.is_phone_camera)]
    if len(CONNECTED_CAMERAS) == initial_len:
        raise HTTPException(status_code=404, detail="Phone camera not found")
    if camera_id in LATEST_PHONE_FRAMES:
        del LATEST_PHONE_FRAMES[camera_id]
    return {"status": "disconnected", "camera_id": camera_id}
