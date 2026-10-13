"""Event persistence, labels, visit matching, occupancy rules, corrections and DB failure handling."""

import time
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import db
import services.events as events_module
from models.entities import CameraIncident, DetectionEvent, User, Visit
from services import occupancy
from services.events import EventRecorder, LinkError, link_exit_to_visit, unlink_exit, update_event
from vision.line_crossing import CrossingEvent

SESSION = "session-a"


def crossing(kind, track_id, t=None, reason=None):
    return CrossingEvent(kind, track_id, t if t is not None else time.time(), 0.82, (10, 10, 60, 160), reason)


def operator():
    with db.session_scope() as s:
        user = s.scalar(select(User).where(User.username == "operator"))
        s.expunge(user)
        return user


@pytest.fixture
def recorder(camera, users, snapshot_dir):
    return EventRecorder()


def test_entry_creates_visit_with_new_label(recorder, camera):
    payload = recorder.record(camera, SESSION, crossing("entry", 7), b"\xff\xd8jpeg")
    assert payload["event_type"] == "entry"
    assert payload["person_label"] == "Unknown Person 01"
    assert payload["has_snapshot"] is True
    with db.session_scope() as s:
        visit = s.scalar(select(Visit))
        assert visit.status == "inside" and visit.person_label == "Unknown Person 01"
        assert occupancy.compute_occupancy(s)["count"] == 1


def test_labels_are_unique_and_sequential(recorder, camera):
    labels = [recorder.record(camera, SESSION, crossing("entry", tid), None)["person_label"] for tid in (1, 2, 3)]
    assert labels == ["Unknown Person 01", "Unknown Person 02", "Unknown Person 03"]


def test_same_track_keeps_its_label(recorder, camera):
    a = recorder.record(camera, SESSION, crossing("entry", 5), None)
    b = recorder.record(camera, SESSION, crossing("exit", 5), None)
    assert a["person_label"] == b["person_label"]


def test_same_tracker_id_in_new_session_is_a_new_person(recorder, camera):
    a = recorder.record(camera, "session-1", crossing("entry", 1), None)
    b = recorder.record(camera, "session-2", crossing("entry", 1), None)
    assert a["person_label"] != b["person_label"]


def test_exit_by_same_track_closes_visit(recorder, camera):
    t0 = time.time()
    recorder.record(camera, SESSION, crossing("entry", 4, t0), None)
    exit_payload = recorder.record(camera, SESSION, crossing("exit", 4, t0 + 90), None)
    assert exit_payload["match_status"] == "matched"
    with db.session_scope() as s:
        visit = s.scalar(select(Visit))
        assert visit.status == "exited" and visit.match_method == "tracker"
        assert (visit.exit_at - visit.entry_at) == timedelta(seconds=90)
        assert occupancy.compute_occupancy(s)["count"] == 0


def test_exit_without_continuity_is_unmatched_and_does_not_close_visits(recorder, camera):
    t0 = time.time()
    recorder.record(camera, SESSION, crossing("entry", 1, t0), None)
    payload = recorder.record(camera, SESSION, crossing("exit", 2, t0 + 5), None)  # different track
    assert payload["match_status"] == "unmatched"
    assert payload["person_label"] == "Unknown Person 02"
    with db.session_scope() as s:
        assert s.scalar(select(Visit)).status == "inside"  # never paired just by time
        assert occupancy.compute_occupancy(s)["count"] == 0  # the exit still counts


def test_occupancy_never_negative_and_flags_missed_entry(recorder, camera):
    recorder.record(camera, SESSION, crossing("exit", 1), None)
    with db.session_scope() as s:
        occ = occupancy.compute_occupancy(s)
    assert occ["count"] == 0
    assert occ["estimated"] is True
    assert "missed" in occ["reasons"][0]


def test_uncertain_events_do_not_count_and_mark_estimate(recorder, camera):
    recorder.record(camera, SESSION, crossing("entry", 1), None)
    payload = recorder.record(camera, SESSION, crossing("uncertain", 2, reason="lost_while_crossing"), None)
    assert payload["review_status"] == "needs_review"
    with db.session_scope() as s:
        occ = occupancy.compute_occupancy(s)
    assert occ["count"] == 1 and occ["estimated"] is True


def test_reconcile_sets_baseline_and_clears_estimate(recorder, camera):
    recorder.record(camera, SESSION, crossing("exit", 1, time.time() - 60), None)
    user = operator()
    with db.session_scope() as s:
        occupancy.reconcile(s, user, 3, "Head count at night roll call")
    recorder.record(camera, SESSION, crossing("entry", 2), None)
    with db.session_scope() as s:
        occ = occupancy.compute_occupancy(s)
    assert occ["count"] == 4 and occ["estimated"] is False


def test_manual_adjustment_counts_and_is_audited(recorder, camera):
    user = operator()
    with db.session_scope() as s:
        occupancy.adjust(s, user, 2, "Two residents entered through the side gate")
    with db.session_scope() as s:
        assert occupancy.compute_occupancy(s)["count"] == 2
        from models.entities import AuditLog

        assert s.scalar(select(AuditLog).where(AuditLog.action == "occupancy.adjust")) is not None


def test_camera_interruption_marks_estimate(recorder, camera):
    with db.session_scope() as s:
        s.add(CameraIncident(camera_id=camera, kind="disconnected", message="No frames"))
        occ = occupancy.compute_occupancy(s)
    assert occ["estimated"] is True and "interruption" in occ["reasons"][0]


def test_correcting_uncertain_to_entry_opens_visit(recorder, camera):
    payload = recorder.record(camera, SESSION, crossing("uncertain", 3, reason="direction_reversal"), None)
    user = operator()
    with db.session_scope() as s:
        event = s.get(DetectionEvent, payload["id"])
        update_event(s, event, user, event_type="entry")
    with db.session_scope() as s:
        event = s.get(DetectionEvent, payload["id"])
        assert event.review_status == "corrected" and event.original_event_type == "uncertain"
        assert s.get(Visit, event.visit_id).status == "inside"
        assert occupancy.compute_occupancy(s)["count"] == 1


def test_rejecting_entry_voids_visit_and_restores_count(recorder, camera):
    payload = recorder.record(camera, SESSION, crossing("entry", 3), None)
    user = operator()
    with db.session_scope() as s:
        update_event(s, s.get(DetectionEvent, payload["id"]), user, review_status="rejected")
    with db.session_scope() as s:
        assert s.scalar(select(Visit)).status == "voided"
        assert occupancy.compute_occupancy(s)["count"] == 0


def test_rejecting_matched_exit_reopens_visit(recorder, camera):
    recorder.record(camera, SESSION, crossing("entry", 3), None)
    exit_payload = recorder.record(camera, SESSION, crossing("exit", 3), None)
    user = operator()
    with db.session_scope() as s:
        update_event(s, s.get(DetectionEvent, exit_payload["id"]), user, review_status="rejected")
    with db.session_scope() as s:
        visit = s.scalar(select(Visit))
        assert visit.status == "inside" and visit.exit_at is None


def test_operator_links_unmatched_exit_and_can_unlink(recorder, camera):
    t0 = time.time()
    entry = recorder.record(camera, SESSION, crossing("entry", 1, t0), None)
    exit_payload = recorder.record(camera, "other-session", crossing("exit", 9, t0 + 600), None)
    user = operator()
    with db.session_scope() as s:
        visit = s.get(Visit, entry["visit_id"])
        link_exit_to_visit(s, visit, s.get(DetectionEvent, exit_payload["id"]), user)
    with db.session_scope() as s:
        visit = s.get(Visit, entry["visit_id"])
        event = s.get(DetectionEvent, exit_payload["id"])
        assert visit.status == "exited" and visit.match_method == "manual"
        assert event.person_label == entry["person_label"] and event.match_status == "matched"
        unlink_exit(s, event, user)
    with db.session_scope() as s:
        event = s.get(DetectionEvent, exit_payload["id"])
        assert s.get(Visit, entry["visit_id"]).status == "inside"
        assert event.match_status == "unmatched" and event.person_label == exit_payload["person_label"]


def test_cannot_link_exit_that_precedes_entry(recorder, camera):
    t0 = time.time()
    exit_payload = recorder.record(camera, SESSION, crossing("exit", 2, t0 - 600), None)
    entry = recorder.record(camera, SESSION, crossing("entry", 1, t0), None)
    with db.session_scope() as s:
        with pytest.raises(LinkError):
            link_exit_to_visit(s, s.get(Visit, entry["visit_id"]), s.get(DetectionEvent, exit_payload["id"]), operator())


def test_database_failure_queues_event_until_write_succeeds(recorder, camera, monkeypatch):
    real = events_module.persist_crossing
    calls = {"n": 0}

    def flaky(session, item):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("INSERT", {}, Exception("database is locked"))
        return real(session, item)

    broadcasts = []
    recorder.on_recorded = broadcasts.append
    monkeypatch.setattr(events_module, "persist_crossing", flaky)

    assert recorder.record(camera, SESSION, crossing("entry", 1), b"jpeg") is None
    assert recorder.pending_count() == 1 and broadcasts == []  # not reported as persisted
    with db.session_scope() as s:
        assert s.scalar(select(DetectionEvent)) is None

    assert recorder.retry_pending() == 1
    assert recorder.pending_count() == 0 and len(broadcasts) == 1
    with db.session_scope() as s:
        assert s.scalar(select(DetectionEvent)).snapshot_status == "saved"


def test_low_storage_skips_snapshot_but_keeps_event(recorder, camera, monkeypatch):
    import services.snapshots as snapshots

    monkeypatch.setattr(snapshots, "storage_status", lambda: {"free_mb": 1, "low": True, "min_free_mb": 500})
    payload = recorder.record(camera, SESSION, crossing("entry", 1), b"jpeg")
    assert payload["snapshot_status"] == "skipped_low_storage" and payload["has_snapshot"] is False
