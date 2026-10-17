"""Camera worker pipeline with synthetic frames, a scripted detector and fake stream readers."""

import threading
import time

import numpy as np
import pytest
from sqlalchemy import select

import db
from models.entities import CameraIncident, DetectionEvent
from services.events import EventRecorder
from services.incidents import close_incidents, open_incident
from services.snapshots import snapshot_file
from vision.camera_worker import CameraSpec, CameraWorker
from vision.line_crossing import CrossingParams, Detection, LineConfig

LINE = LineConfig(0.1, 0.5, 0.9, 0.5, entry_side=1)
PARAMS = CrossingParams(min_confidence=0.4, track_timeout_seconds=30, min_track_hits=2, min_side_frames=2, anchor="center")


def frame():
    img = np.full((480, 640, 3), 90, dtype=np.uint8)
    img[200:300, 280:360] = (40, 160, 220)
    return img


class ScriptedDetector:
    """Returns one scripted position per call: a person walking down through the line."""

    def __init__(self, ys=(100, 140, 180, 220, 260, 300, 340, 380)):
        self.ys = list(ys)
        self.calls = 0
        self.resets = 0

    def track(self, _frame):
        y = self.ys[min(self.calls, len(self.ys) - 1)]
        self.calls += 1
        return [Detection(1, (290, y - 60, 350, y + 60), 0.88)]

    def reset(self):
        self.resets += 1


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def make_worker(spec, detector_factory, recorder=None, reader_factory=None, stale=5.0):
    return CameraWorker(
        spec,
        params_provider=lambda: PARAMS,
        detector_factory=detector_factory,
        recorder=recorder or EventRecorder(),
        reader_factory=reader_factory,
        on_interruption=open_incident,
        on_recovery=close_incidents,
        stale_seconds=stale,
        detection_max_fps=200,
        viewer_max_fps=50,
    )


@pytest.fixture
def browser_spec(camera):
    return CameraSpec(id=camera, name="Main Entrance", source_type="browser", source=None, line=LINE)


def push_frames(worker, n, delay=0.03):
    for _ in range(n):
        worker.push_frame(frame())
        time.sleep(delay)


def test_not_live_until_frames_arrive(browser_spec, snapshot_dir):
    worker = make_worker(browser_spec, ScriptedDetector)
    worker.start()
    try:
        assert worker.status == "connecting"
        worker.push_frame(frame())
        assert worker.status == "live" and worker.last_frame_at is not None
    finally:
        worker.stop()


def test_entry_is_recorded_with_snapshot(browser_spec, snapshot_dir):
    worker = make_worker(browser_spec, ScriptedDetector)
    worker.start()
    try:
        push_frames(worker, 15)
        assert wait_for(lambda: worker.events_recorded >= 1)
    finally:
        worker.stop()
    with db.session_scope() as s:
        events = s.scalars(select(DetectionEvent)).all()
        assert [e.event_type for e in events] == ["entry"]
        assert events[0].snapshot_status == "saved"
        path = snapshot_file(events[0].snapshot_path)
        assert path is not None and path.read_bytes()[:2] == b"\xff\xd8"  # a real JPEG crop


def test_jpeg_frames_from_browser_are_decoded(browser_spec, snapshot_dir):
    import cv2

    ok, buf = cv2.imencode(".jpg", frame())
    worker = make_worker(browser_spec, ScriptedDetector)
    worker.start()
    try:
        for _ in range(15):
            worker.push_frame(buf.tobytes())
            time.sleep(0.03)
        assert wait_for(lambda: worker.events_recorded >= 1)
        assert worker.snapshot()["frame_size"] == (640, 480)
    finally:
        worker.stop()


def test_disconnection_is_detected_and_logged(browser_spec, snapshot_dir):
    detector = ScriptedDetector(ys=(100, 140, 180))
    worker = make_worker(browser_spec, lambda: detector, stale=0.4)
    worker.start()
    try:
        push_frames(worker, 4)
        session_before = worker.session_id
        assert wait_for(lambda: worker.status == "disconnected", timeout=3)
        assert worker.session_id != session_before  # tracker IDs restart: new session
        assert detector.resets == 1
        with db.session_scope() as s:
            incident = s.scalar(select(CameraIncident))
            assert incident.kind == "disconnected" and incident.ended_at is None
        worker.push_frame(frame())  # frames resume
        assert worker.status == "live"
        with db.session_scope() as s:
            assert s.scalar(select(CameraIncident)).ended_at is not None
    finally:
        worker.stop()


def test_unreachable_network_camera_reports_error(camera):
    class DeadReader:
        is_file = False

        def __init__(self, *_):
            pass

        def connect(self):
            return False

        def release(self):
            pass

    spec = CameraSpec(id=camera, name="IP", source_type="network", source="rtsp://10.0.0.9/stream", line=LINE)
    worker = make_worker(spec, ScriptedDetector, reader_factory=DeadReader)
    worker.start()
    try:
        assert wait_for(lambda: worker.status == "error")
        assert "Could not open the camera stream" in worker.message
        assert "10.0.0.9" not in worker.message  # never echo the source
        assert worker.last_frame_at is None
    finally:
        worker.stop(join=False)


def test_stalled_stream_reconnects(camera):
    opened = []

    class StallingReader:
        is_file = False

        def __init__(self, *_):
            self.n = 0

        def connect(self):
            opened.append(1)
            return True

        def read_frame(self):
            self.n += 1
            return frame() if self.n <= 3 else None

        def release(self):
            pass

    spec = CameraSpec(id=camera, name="IP", source_type="network", source="rtsp://x/y", line=LINE)
    worker = make_worker(spec, ScriptedDetector, reader_factory=StallingReader)
    worker.start()
    try:
        assert wait_for(lambda: len(opened) >= 2, timeout=6)
    finally:
        worker.stop()


def test_missing_detector_keeps_live_view(browser_spec):
    worker = make_worker(browser_spec, lambda: None)
    worker.start()
    try:
        push_frames(worker, 3)
        assert wait_for(lambda: worker.detection_status == "unavailable")
        assert worker.status == "live"
    finally:
        worker.stop()


def test_detector_load_failure_is_reported(browser_spec):
    def broken():
        raise RuntimeError("weights corrupt")

    worker = make_worker(browser_spec, broken)
    worker.start()
    try:
        push_frames(worker, 2)
        assert wait_for(lambda: worker.detection_status == "error")
        assert worker.status == "live"
    finally:
        worker.stop()


def test_worker_crash_surfaces_as_error(browser_spec):
    class ExplodingRecorder:
        def record(self, *args):
            raise RuntimeError("boom")

    worker = make_worker(browser_spec, ScriptedDetector, recorder=ExplodingRecorder())
    worker.start()
    try:
        push_frames(worker, 15)
        assert wait_for(lambda: worker.status == "error")
        assert "Camera worker failed" in worker.message
    finally:
        worker.stop()


def test_viewer_frames_include_overlay(browser_spec):
    received = []
    ready = threading.Event()

    class Viewer:
        def has_viewers(self, _):
            return True

        def publish_frame(self, _cid, payload):
            received.append(payload)
            ready.set()

        def publish_status(self, *_):
            pass

    worker = CameraWorker(browser_spec, lambda: PARAMS, ScriptedDetector, EventRecorder(), publisher=Viewer(), detection_max_fps=200, viewer_max_fps=50)
    worker.start()
    try:
        push_frames(worker, 6)
        assert ready.wait(3)
        payload = received[-1]
        assert payload["image"].startswith("data:image/jpeg;base64,")
        assert payload["line"]["entry_side"] == 1
    finally:
        worker.stop()


# -- Regression: stale interruption warnings ------------------------------------------------

class DeadReader:
    is_file = False

    def __init__(self, *_):
        pass

    def connect(self):
        return False

    def release(self):
        pass


def _open_incidents():
    with db.session_scope() as s:
        return [(i.kind, i.ended_at) for i in s.scalars(select(CameraIncident))]


def test_replacement_worker_closes_incident_left_by_previous_worker(browser_spec):
    """Reconnect / source change creates a new worker; its first frame must close old incidents."""
    open_incident(browser_spec.id, "error", "Camera stream could not be reopened.")
    worker = make_worker(browser_spec, ScriptedDetector)  # fresh worker, status "connecting"
    worker.start()
    try:
        worker.push_frame(frame())
        assert worker.status == "live"
        assert all(ended is not None for _, ended in _open_incidents())
    finally:
        worker.stop()


def test_setup_failure_before_first_frame_is_not_an_interruption(camera):
    spec = CameraSpec(id=camera, name="IP", source_type="network", source="rtsp://10.0.0.9/x", line=LINE)
    worker = make_worker(spec, ScriptedDetector, reader_factory=DeadReader)
    worker.start()
    try:
        assert wait_for(lambda: worker.status == "error")
        assert _open_incidents() == []  # never monitored: shown as camera error, not missed events
    finally:
        worker.stop(join=False)


def test_failure_after_monitoring_is_an_interruption(camera):
    spec = CameraSpec(id=camera, name="IP", source_type="network", source="rtsp://10.0.0.9/x", line=LINE)
    worker = CameraWorker(spec, lambda: PARAMS, ScriptedDetector, EventRecorder(), reader_factory=DeadReader,
                          on_interruption=open_incident, on_recovery=close_incidents, monitoring_established=True)
    worker.start()
    try:
        assert wait_for(lambda: worker.status == "disconnected")
        assert [k for k, ended in _open_incidents() if ended is None] == ["error"]
    finally:
        worker.stop(join=False)


def test_occupancy_reason_distinguishes_ongoing_and_resolved(camera):
    from services.occupancy import compute_occupancy

    open_incident(camera, "disconnected", "No frames")
    with db.session_scope() as s:
        assert "is not delivering video" in compute_occupancy(s, 1)["reasons"][0]
    close_incidents(camera)
    with db.session_scope() as s:
        occ = compute_occupancy(s, 1)
        assert occ["estimated"] is True  # still flagged: events may have been missed during the gap
        assert "earlier camera interruption" in occ["reasons"][0]


def test_zone_events_reach_the_sink_with_evidence_and_quality_is_measured(camera, snapshot_dir):
    from services.evidence import EvidencePolicy
    from vision.zones import ZoneConfig

    received = []
    zone = ZoneConfig(5, "Counter", "restricted", ((0.3, 0.0), (0.7, 0.0), (0.7, 1.0), (0.3, 1.0)))
    spec = CameraSpec(id=camera, name="Main Entrance", source_type="browser", source=None, line=LINE,
                      organization_id=1, location_id=1, zones=(zone,))
    worker = CameraWorker(
        spec, params_provider=lambda: PARAMS, detector_factory=ScriptedDetector, recorder=EventRecorder(),
        detection_max_fps=200, viewer_max_fps=50,
        zone_sink=lambda s, session, ev, jpeg: received.append((ev, jpeg)),
        evidence_policy=lambda: EvidencePolicy(jpeg_quality=60, max_width=32, storage_limit_mb=10),
    )
    worker.start()
    try:
        push_frames(worker, 15)
        assert wait_for(lambda: len(received) >= 1)
        assert wait_for(lambda: worker.quality is not None)
    finally:
        worker.stop()
    ev, jpeg = received[0]
    assert ev.kind == "zone_entered" and ev.zone_id == 5 and jpeg[:2] == b"\xff\xd8"
    import cv2

    img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[1] <= 32  # evidence policy max width applied
    assert set(worker.snapshot()["quality"]) == {"brightness", "contrast", "sharpness", "measured_at"}


def test_counting_disabled_camera_records_no_crossings(camera):
    from models.entities import Camera
    from vision.camera_manager import line_from_camera

    with db.session_scope() as s:
        cam = s.get(Camera, camera)
        cam.line_x1, cam.line_y1, cam.line_x2, cam.line_y2 = 0.1, 0.5, 0.9, 0.5
        assert line_from_camera(cam) is not None
        cam.counting_enabled = False
        assert line_from_camera(cam) is None
