"""Anomaly integration boundary: never invents alerts, never blocks, surfaces failures."""

import threading
import time

import numpy as np

from vision.anomaly import AnomalyDetectorAdapter

FRAME = np.zeros((240, 320, 3), dtype=np.uint8)


def feed(adapter, n, camera="CAM-1"):
    for i in range(n):
        adapter.process_frame(camera, FRAME, time.time())


def wait(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        time.sleep(0.02)
    return predicate()


def test_disabled_by_default_does_nothing():
    events = []
    adapter = AnomalyDetectorAdapter(on_event=events.append, enabled=False)
    assert adapter.initialize_anomaly_detector() is False
    feed(adapter, 50)
    assert adapter.health_check()["status"] == "disabled" and events == []


def test_real_detector_without_weights_runs_motion_mode_and_stays_quiet_on_empty_frames():
    """Loads the real edge-agent/fight_detector.py: no FIGHT_MODEL_PATH -> weight-free motion mode."""
    events = []
    adapter = AnomalyDetectorAdapter(on_event=events.append, enabled=True, sample_every_n_frames=1, clip_length=4)
    assert adapter.initialize_anomaly_detector() is True
    try:
        health = adapter.health_check()
        assert health["status"] == "motion" and health["mode"] == "motion"
        assert "not fights" in health["message"]
        feed(adapter, 12)
        assert wait(lambda: adapter.processed_clips >= 1)
        assert events == []
    finally:
        adapter.shutdown()


def test_model_initialisation_failure_is_reported():
    def broken():
        raise RuntimeError("weights missing")

    adapter = AnomalyDetectorAdapter(on_event=lambda e: None, enabled=True, detector_factory=broken)
    assert adapter.initialize_anomaly_detector() is False
    assert adapter.health_check()["status"] == "error"
    feed(adapter, 10)  # must be a no-op, not raise


class Model:
    model = object()  # looks like a loaded model

    def __init__(self, output=None, error=None, delay=0.0):
        self.output, self.error, self.delay = output, error, delay

    def predict_clip(self, clip):
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.output


def test_inference_failure_sets_error_and_creates_no_events():
    events = []
    adapter = AnomalyDetectorAdapter(events.append, enabled=True, detector_factory=lambda: Model(error=ValueError("bad tensor")), sample_every_n_frames=1, clip_length=2)
    adapter.initialize_anomaly_detector()
    try:
        feed(adapter, 4)
        assert wait(lambda: adapter.failed_inferences >= 1)
        assert adapter.health_check()["status"] == "error" and events == []
    finally:
        adapter.shutdown()


def test_only_real_positive_outputs_above_threshold_are_recorded():
    events = []
    output = {"is_fight": True, "confidence_score": 0.91, "threshold": 0.75}
    adapter = AnomalyDetectorAdapter(events.append, enabled=True, detector_factory=lambda: Model(output=output), sample_every_n_frames=1, clip_length=2, threshold=0.75, min_consecutive=1)
    adapter.initialize_anomaly_detector()
    try:
        feed(adapter, 2)
        assert wait(lambda: len(events) == 1)
        assert events[0].confidence == 0.91 and events[0].camera_id == "CAM-1"
    finally:
        adapter.shutdown()

    low = []
    adapter = AnomalyDetectorAdapter(low.append, enabled=True, detector_factory=lambda: Model(output={"is_fight": True, "confidence_score": 0.5}), sample_every_n_frames=1, clip_length=2, threshold=0.75, min_consecutive=1)
    adapter.initialize_anomaly_detector()
    try:
        feed(adapter, 2)
        assert wait(lambda: adapter.processed_clips == 1)
        assert low == []
    finally:
        adapter.shutdown()


def test_slow_model_never_blocks_the_camera():
    adapter = AnomalyDetectorAdapter(lambda e: None, enabled=True, detector_factory=lambda: Model(output={}, delay=1.0), sample_every_n_frames=1, clip_length=1)
    adapter.initialize_anomaly_detector()
    try:
        started = time.perf_counter()
        feed(adapter, 40)
        assert time.perf_counter() - started < 0.5  # 40 frames queued/dropped without waiting on inference
        assert adapter.dropped_clips > 0
        assert threading.active_count() < 50
    finally:
        adapter.shutdown()
