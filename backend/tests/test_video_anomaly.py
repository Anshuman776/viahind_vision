"""Video anomaly detector: motion mode, the trainable classifier, safe loading, and alerting.

SYNTHETIC TEST FIXTURES ONLY: the "videos" below are generated noise/colour patterns used to exercise
the code paths. They say nothing about real-world accuracy and must never be used as training data.
"""

import json
import time

import cv2
import numpy as np
import pytest
from sqlalchemy import select

import db
from models.entities import Alert
from vision import fight_model, motion_anomaly
from vision.anomaly import AnomalyDetectorAdapter
from vision.edge_agent import load_edge_agent_module

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")

TWO_CLOSE = [(0.30, 0.30, 0.50, 0.90), (0.45, 0.30, 0.65, 0.90)]  # normalised boxes, overlapping people
ONE_PERSON = [(0.30, 0.30, 0.50, 0.90)]


def scuffle_clip(n=8, seed=0, moving=True):
    """Static background; a textured block inside the people region that jumps around when moving."""
    rng = np.random.default_rng(seed)
    background = np.full((224, 224, 3), 120, np.uint8)
    texture = cv2.GaussianBlur(rng.integers(0, 255, (60, 60, 3), dtype=np.uint8), (0, 0), 3)
    texture = cv2.normalize(texture, None, 0, 255, cv2.NORM_MINMAX)
    frames = []
    for i in range(n):
        f = background.copy()
        # Back-and-forth movement of about 10 px per frame, like arms and bodies in a scuffle.
        dx, dy = ((10, 6) if i % 2 else (-10, -6)) if moving else (0, 0)
        if moving:
            dx, dy = dx + int(rng.integers(-2, 3)), dy + int(rng.integers(-2, 3))
        y, x = 110 + dy, 100 + dx
        f[y:y + 60, x:x + 60] = texture
        frames.append(f)
    return frames


# -- motion mode -----------------------------------------------------------------------------------------

def test_motion_mode_flags_vigorous_movement_between_people_in_contact():
    result = motion_anomaly.analyse_clip(scuffle_clip(), [TWO_CLOSE] * 8)
    assert result["is_anomaly"] and result["confidence_score"] > 0
    assert result["metrics"]["people_in_contact"] == 2


@pytest.mark.parametrize("people,moving", [([ONE_PERSON] * 8, True), ([TWO_CLOSE] * 8, False), ([[]] * 8, True)])
def test_motion_mode_ignores_single_people_still_scenes_and_empty_frames(people, moving):
    assert not motion_anomaly.analyse_clip(scuffle_clip(moving=moving), people)["is_anomaly"]


def test_motion_mode_ignores_whole_frame_camera_shake():
    rng = np.random.default_rng(1)
    base = rng.integers(0, 255, (300, 300, 3), dtype=np.uint8)
    frames = []
    for _ in range(8):
        ox, oy = rng.integers(0, 60, 2)
        frames.append(cv2.resize(base[oy:oy + 224, ox:ox + 224], (224, 224)))
    assert not motion_anomaly.analyse_clip(frames, [TWO_CLOSE] * 8)["is_anomaly"]


def test_detector_without_weights_uses_motion_mode_and_labels_honestly():
    detector = load_edge_agent_module("fight_detector").FightDetector(model_path="", mode="auto")
    assert detector.mode == "motion" and detector.model is None
    out = detector.predict_clip(scuffle_clip(), people=[TWO_CLOSE] * 8)
    assert out["is_anomaly"] and out["is_fight"] is False and out["label"] == "Vigorous movement between people"
    assert detector.predict_clip(scuffle_clip())["is_anomaly"] is False  # needs people boxes
    with pytest.raises(FileNotFoundError):
        load_edge_agent_module("fight_detector").FightDetector(model_path="", mode="model")


# -- trainable classifier ---------------------------------------------------------------------------------

def _write_video(path, frames, fps=10):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frames[0].shape[1], frames[0].shape[0]))
    for f in frames:
        writer.write(f)
    writer.release()


@pytest.fixture
def synthetic_dataset(tmp_path):
    """Synthetic fixture: 'fight' = moving red noise, 'nonfight' = still blue scene."""
    for label, moving in (("fight", True), ("nonfight", False)):
        folder = tmp_path / "data" / label
        folder.mkdir(parents=True)
        for k in range(3):
            frames = [cv2.resize(f, (96, 96)) for f in scuffle_clip(n=20, seed=k, moving=moving)]
            if moving:
                frames = [cv2.add(f, np.array([0, 0, 80], np.uint8)) for f in frames]
            _write_video(folder / f"clip{k}.mp4", frames)
    return tmp_path / "data"


def test_dataset_discovery_and_metrics(synthetic_dataset):
    items = fight_model.find_dataset(synthetic_dataset)
    assert sorted(y for _, y in items) == [0, 0, 0, 1, 1, 1]
    m = fight_model.binary_metrics([1, 1, 0, 0], [0.9, 0.4, 0.2, 0.8], 0.5)
    assert (m["true_positives"], m["false_negatives"], m["false_positives"], m["true_negatives"]) == (1, 1, 1, 1)
    assert m["accuracy"] == 0.5 and m["f1"] == 0.5


def test_train_save_load_and_predict(synthetic_dataset, tmp_path):
    result = fight_model.train(synthetic_dataset, tmp_path / "out", epochs=1, batch_size=2, log=lambda _m: None)
    weights = tmp_path / "out" / result["weights"].split("\\")[-1].split("/")[-1]
    meta = json.loads(weights.with_suffix(".json").read_text())
    assert meta["model_name"] == fight_model.MODEL_NAME and meta["sha256"] == fight_model.sha256_file(weights)
    assert set(meta["holdout_metrics"]) >= {"accuracy", "precision", "recall", "f1", "threshold"}

    detector = load_edge_agent_module("fight_detector").FightDetector(model_path=str(weights), mode="auto")
    assert detector.mode == "model" and detector.model_version == meta["version"]
    out = detector.predict_clip(scuffle_clip(n=16))
    assert 0.0 <= out["confidence_score"] <= 1.0 and out["mode"] == "model" and out["requires_human_verification"]

    # Tampered weights are refused.
    weights.write_bytes(weights.read_bytes() + b"x")
    with pytest.raises(ValueError):
        fight_model.load_checkpoint(weights)


def test_training_refuses_too_little_data(tmp_path):
    (tmp_path / "fight").mkdir()
    with pytest.raises(ValueError):
        fight_model.train(tmp_path, tmp_path / "out", epochs=1, log=lambda _m: None)


def test_preprocess_validates_input():
    clip = fight_model.preprocess_clip([np.zeros((50, 80, 3), np.uint8)] * 5)
    assert clip.shape == (16, 3, 224, 224)
    with pytest.raises(ValueError):
        fight_model.preprocess_clip([])


# -- adapter and alerts ------------------------------------------------------------------------------------

def test_adapter_requires_consecutive_positive_clips_and_attaches_evidence():
    events = []
    detector = load_edge_agent_module("fight_detector").FightDetector(model_path="", mode="motion")
    adapter = AnomalyDetectorAdapter(events.append, enabled=True, detector_factory=lambda: detector,
                                     sample_every_n_frames=1, clip_length=8, min_consecutive=2)
    adapter.initialize_anomaly_detector()
    people_px = [(b[0] * 224, b[1] * 224, b[2] * 224, b[3] * 224) for b in TWO_CLOSE]
    try:
        for f in scuffle_clip(n=8, seed=3):
            adapter.process_frame("CAM-1", f, time.time(), people_px)
        deadline = time.time() + 10
        while adapter.processed_clips < 1 and time.time() < deadline:
            time.sleep(0.05)
        assert events == []  # one positive clip is not enough
        for f in scuffle_clip(n=8, seed=4):
            adapter.process_frame("CAM-1", f, time.time(), people_px)
        while not events and time.time() < deadline:
            time.sleep(0.05)
    finally:
        adapter.shutdown()
    assert len(events) == 1
    assert events[0].raw_output["mode"] == "motion" and events[0].raw_output["consecutive_clips"] == 2
    assert events[0].snapshot_jpeg[:2] == b"\xff\xd8"


def test_video_anomaly_becomes_reviewable_alert_with_snapshot(camera, snapshot_dir):
    from services import alert_engine
    from services.anomaly_store import store_anomaly
    from vision.anomaly import AnomalyResult

    alert_engine._rule_cache.clear()
    result = AnomalyResult(camera, time.time(), "Vigorous movement between people", 0.6, "VIAHIND-MotionContact", "motion-v1",
                           {"mode": "motion", "consecutive_clips": 2, "metrics": {"people_in_contact": 2, "strong_motion_fraction": 0.75}},
                           snapshot_jpeg=b"\xff\xd8frame")
    stored = store_anomaly(result)
    alert_engine.on_video_anomaly(stored, result.snapshot_jpeg)
    with db.session_scope() as s:
        alert = s.scalar(select(Alert))
        assert alert.rule_type == "video_anomaly_model" and alert.title == "Vigorous movement between people"
        assert "does not recognise fights" in alert.reason and alert.snapshot_status == "saved"
        assert alert.severity == "high"


def test_activation_updates_only_the_model_lines_in_env(tmp_path, monkeypatch):
    import config
    import manage

    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=keep-me\nFIGHT_MODEL_PATH=\n# comment stays\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env)
    manage._set_env({"FIGHT_MODEL_PATH": "C:/m/fight.pt", "FIGHT_MODEL_SHA256": "abc"})
    assert env.read_text(encoding="utf-8").splitlines() == [
        "SECRET_KEY=keep-me", "FIGHT_MODEL_PATH=C:/m/fight.pt", "# comment stays", "FIGHT_MODEL_SHA256=abc"]
