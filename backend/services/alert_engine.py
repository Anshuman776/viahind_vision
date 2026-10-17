"""
Alert engine: turns recorded events, zone observations and system health into reviewable alerts.

Event-driven rules (called right after an event is persisted):
    after_hours, repeated_crossings, traffic_frequency, occupancy
Zone rules (called by camera workers):
    restricted_zone, zone_dwell
Periodic rules (AlertEngine thread, every ALERT_EVAL_INTERVAL_SECONDS):
    camera_offline, camera_quality, processing_error; plus hourly ML inference and scheduled reports.

The engine never blocks a camera worker on failure: every hook catches and logs its own errors.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from db import session_scope, utcnow
from models.entities import Camera, CameraIncident, CameraZone, DetectionEvent, Location, PersonTrack, SyncOutbox
from services.alert_rules import RULES, EffectiveRule, effective_rules
from services.alerts import AlertDraft, auto_resolve, publish, raise_alert
from services.business_hours import is_open, parse_hours
from services.evidence import evidence_policy
from services.guards import guard_allows
from services.occupancy import compute_location_occupancy, occupancy_changes
from services.site_settings import get_site_settings, site_zone
from services.snapshots import save_snapshot

logger = logging.getLogger("viahind.alert_engine")

RULE_CACHE_SECONDS = 20.0
_rule_cache: Dict[int, Tuple[float, Dict[str, EffectiveRule]]] = {}
_rule_lock = threading.Lock()


def rules_for(organization_id: int) -> Dict[str, EffectiveRule]:
    now = time.monotonic()
    with _rule_lock:
        cached = _rule_cache.get(organization_id)
        if cached and now - cached[0] < RULE_CACHE_SECONDS:
            return cached[1]
    with session_scope() as db:
        rules = effective_rules(db, organization_id)
    with _rule_lock:
        _rule_cache[organization_id] = (now, rules)
    return rules


def invalidate_rules(organization_id: int) -> None:
    with _rule_lock:
        _rule_cache.pop(organization_id, None)


def _emit(draft: AlertDraft, rule: EffectiveRule) -> Optional[str]:
    if not guard_allows(draft.organization_id, draft.camera_id, draft.rule_type):
        return None  # not this guard's duty (services/guards.py)
    with session_scope() as db:
        outcome = raise_alert(db, draft, rule.cooldown_seconds)
        db.flush()
        alert_id = outcome.alert.id
    with session_scope() as db:
        from models.entities import Alert

        outcome.alert = db.get(Alert, alert_id)
        publish(db, outcome)
    return alert_id


def _draft(rule: EffectiveRule, organization_id: int, dedup: str, reason: str, occurred_at: datetime, **kw) -> AlertDraft:
    d = RULES[rule.rule_type]
    return AlertDraft(
        organization_id=organization_id, rule_type=rule.rule_type, category=d.category, severity=rule.severity,
        title=kw.pop("title", d.title), reason=reason, dedup_key=dedup, occurred_at=occurred_at, **kw,
    )


# -- event-driven rules ---------------------------------------------------------------------------

def on_event_recorded(event: dict) -> None:
    """Evaluate event-driven rules for one persisted entry/exit/uncertain event."""
    if not settings.ALERTS_ENABLED:
        return
    try:
        _evaluate_event(event)
    except Exception:
        logger.exception("Alert evaluation failed for event %s", event.get("id"))


def _evaluate_event(event: dict) -> None:
    org_id = event.get("organization_id")
    if org_id is None:
        return
    rules = rules_for(org_id)
    occurred = datetime.fromisoformat(event["occurred_at"])
    location_id = event.get("location_id")
    camera_id = event.get("camera_id")
    kind = event.get("event_type")

    with session_scope() as db:
        location = db.get(Location, location_id) if location_id else None
        tz = site_zone(get_site_settings(db, org_id))
        drafts: List[Tuple[AlertDraft, EffectiveRule]] = []

        rule = rules["after_hours"]
        if rule.enabled and location is not None and kind in ("entry", "exit"):
            hours = parse_hours(location.business_hours)
            local = occurred.astimezone(tz)
            if hours is not None and not is_open(local, hours, int(rule.params["grace_minutes"])):
                drafts.append((_draft(
                    rule, org_id, f"after_hours:{location.id}:{local:%Y-%m-%d}",
                    f"{'An entry' if kind == 'entry' else 'An exit'} was recorded at {local:%H:%M} on {local:%A}, "
                    f"outside {location.name}'s business hours.",
                    occurred, location_id=location.id, camera_id=camera_id, event_id=event["id"],
                    track_label=event.get("person_label"),
                    metrics={"local_time": local.strftime("%Y-%m-%d %H:%M"), "event_type": kind,
                             "grace_minutes": rule.params["grace_minutes"]},
                ), rule))

        rule = rules["repeated_crossings"]
        if rule.enabled and kind in ("entry", "exit"):
            track_id = db.scalar(select(DetectionEvent.track_id).where(DetectionEvent.id == event["id"]))
            if track_id is not None:
                window = timedelta(minutes=int(rule.params["window_minutes"]))
                n = db.scalar(select(func.count()).select_from(DetectionEvent).where(
                    DetectionEvent.track_id == track_id,
                    DetectionEvent.event_type.in_(("entry", "exit")),
                    DetectionEvent.occurred_at > occurred - window,
                    DetectionEvent.occurred_at <= occurred,
                )) or 0
                if n >= int(rule.params["min_crossings"]):
                    label = event.get("person_label")
                    drafts.append((_draft(
                        rule, org_id, f"repeated_crossings:{track_id}",
                        f"{label} (a temporary tracking label) crossed the counting line {n} times within "
                        f"{rule.params['window_minutes']} minutes. This can be pacing at the door or a tracking fault.",
                        occurred, location_id=location_id, camera_id=camera_id, event_id=event["id"], track_label=label,
                        metrics={"crossings": n, "window_minutes": rule.params["window_minutes"]},
                    ), rule))

        rule = rules["traffic_frequency"]
        if rule.enabled and camera_id and kind in ("entry", "exit"):
            window = timedelta(minutes=int(rule.params["window_minutes"]))
            n = db.scalar(select(func.count()).select_from(DetectionEvent).where(
                DetectionEvent.camera_id == camera_id,
                DetectionEvent.event_type.in_(("entry", "exit")),
                DetectionEvent.review_status != "rejected",
                DetectionEvent.occurred_at > occurred - window,
                DetectionEvent.occurred_at <= occurred,
            )) or 0
            if n > int(rule.params["max_events"]):
                drafts.append((_draft(
                    rule, org_id, f"traffic_frequency:{camera_id}",
                    f"{n} entries and exits were recorded on {event.get('camera_name') or camera_id} in the last "
                    f"{rule.params['window_minutes']} minutes (threshold {rule.params['max_events']}).",
                    occurred, location_id=location_id, camera_id=camera_id,
                    metrics={"events_in_window": n, "window_minutes": rule.params["window_minutes"], "threshold": rule.params["max_events"]},
                ), rule))

        rule = rules["occupancy"]
        if rule.enabled and location is not None and kind in ("entry", "exit"):
            occ = compute_location_occupancy(db, org_id, location)
            if rule.params["use_capacity"] and location.capacity and occ["count"] > location.capacity:
                drafts.append((_draft(
                    rule, org_id, f"occupancy_capacity:{location.id}",
                    f"Estimated occupancy at {location.name} is {occ['count']}, above its configured capacity of {location.capacity}."
                    + (" The figure is an estimate (see the Overview page for reasons)." if occ["estimated"] else ""),
                    occurred, title="Occupancy above capacity", location_id=location.id,
                    metrics={"occupancy": occ["count"], "capacity": location.capacity, "estimated": occ["estimated"]},
                ), rule))
            window = timedelta(minutes=int(rule.params["window_minutes"]))
            net = sum(d for _, d in occupancy_changes(db, org_id, location.id, occurred - window, occurred))
            if abs(net) > int(rule.params["max_change"]):
                drafts.append((_draft(
                    rule, org_id, f"occupancy_change:{location.id}",
                    f"Occupancy at {location.name} changed by {net:+d} within {rule.params['window_minutes']} minutes "
                    f"(threshold ±{rule.params['max_change']}).",
                    occurred, title="Sudden occupancy change", location_id=location.id,
                    metrics={"net_change": net, "window_minutes": rule.params["window_minutes"], "threshold": rule.params["max_change"]},
                ), rule))

    for draft, rule in drafts:
        _emit(draft, rule)


# -- zone rules -----------------------------------------------------------------------------------

def on_zone_event(spec, session_id: str, zone_event, jpeg: Optional[bytes]) -> None:
    """Called by camera workers (spec: vision.camera_worker.CameraSpec)."""
    if not settings.ALERTS_ENABLED or spec.organization_id is None:
        return
    try:
        _evaluate_zone_event(spec, session_id, zone_event, jpeg)
    except Exception:
        logger.exception("Zone alert failed on camera %s", spec.id)


def _evaluate_zone_event(spec, session_id: str, ev, jpeg: Optional[bytes]) -> None:
    org_id = spec.organization_id
    rules = rules_for(org_id)
    rule = rules["restricted_zone" if ev.kind == "zone_entered" else "zone_dwell"]
    if not rule.enabled or not guard_allows(org_id, spec.id, rule.rule_type):
        return
    occurred = datetime.fromtimestamp(ev.occurred_at, tz=timezone.utc)
    with session_scope() as db:
        label = db.scalar(select(PersonTrack.person_label).where(
            PersonTrack.camera_id == spec.id, PersonTrack.session_id == session_id, PersonTrack.tracker_id == ev.track_id
        ))
    label = label or f"Track {ev.track_id} (temporary)"
    alert_key = f"{rule.rule_type}:{ev.zone_id}"
    policy = evidence_policy(org_id)
    rel, status = save_snapshot(f"zone-{ev.zone_id}-{session_id[:8]}-{ev.track_id}-{int(ev.occurred_at)}", occurred, jpeg,
                                org_id, policy.storage_limit_mb, kind="alerts")
    if ev.kind == "zone_entered":
        reason = f"{label} was detected inside the restricted zone '{ev.zone_name}' on {spec.name}."
    else:
        reason = (f"{label} has been in zone '{ev.zone_name}' on {spec.name} for at least {int(ev.dwell_seconds)} seconds "
                  f"(continuous tracking; the true time may be longer).")
    _emit(_draft(
        rule, org_id, alert_key, reason, occurred,
        location_id=spec.location_id, camera_id=spec.id, zone_id=ev.zone_id, track_label=label,
        snapshot_path=rel, snapshot_status=status,
        metrics={"zone": ev.zone_name, "zone_kind": ev.zone_kind, "dwell_seconds": round(ev.dwell_seconds, 1),
                 "detection_confidence": round(ev.confidence, 2), "tracker_id": ev.track_id},
    ), rule)


# -- video model ----------------------------------------------------------------------------------

def on_video_anomaly(stored: Optional[dict], jpeg: Optional[bytes] = None) -> None:
    if not settings.ALERTS_ENABLED or not stored:
        return
    try:
        org_id = stored["organization_id"]
        rule = rules_for(org_id)["video_anomaly_model"]
        if not rule.enabled or not guard_allows(org_id, stored.get("camera_id"), rule.rule_type):
            return
        with session_scope() as db:
            cam = db.get(Camera, stored["camera_id"]) if stored.get("camera_id") else None
            location_id = cam.location_id if cam else None
            camera_name = cam.name if cam else stored.get("camera_id")
        raw = stored.get("raw_output") or {}
        mode = raw.get("mode", "model")
        occurred = datetime.fromisoformat(stored["occurred_at"])
        policy = evidence_policy(org_id)
        rel, status = save_snapshot(f"video-{stored['id']}", occurred, jpeg, org_id, policy.storage_limit_mb, kind="alerts")
        metrics = {"confidence": stored["confidence"], "consecutive_clips": raw.get("consecutive_clips"), "mode": mode}
        metrics.update(raw.get("metrics") or {})
        if mode == "motion":
            m = raw.get("metrics") or {}
            reason = (f"Vigorous movement between {m.get('people_in_contact', 2)} people in close contact on {camera_name}: strong local motion "
                      f"in {int(100 * (m.get('strong_motion_fraction') or 0))}% of the analysed frames, over "
                      f"{raw.get('consecutive_clips', 1)} consecutive clips. This motion measure does not recognise fights; "
                      "it is often caused by hugging, play or crowding. Check the snapshot or footage.")
            title = "Vigorous movement between people"
        else:
            reason = (f"The video classifier {stored['model_name']} ({stored['model_version']}) estimated a probability of "
                      f"{stored['confidence']:.2f} for '{stored['label']}' on {camera_name} over "
                      f"{raw.get('consecutive_clips', 1)} consecutive clips. Model outputs can be wrong; verify the footage before taking any action.")
            title = "Possible physical altercation (model)"
        _emit(_draft(
            rule, org_id, f"video_anomaly_model:{stored.get('camera_id')}", reason, occurred,
            title=title, location_id=location_id, camera_id=stored.get("camera_id"),
            model_score=stored["confidence"], metrics=metrics, snapshot_path=rel, snapshot_status=status,
        ), rule)
    except Exception:
        logger.exception("Video anomaly alert failed")


# -- periodic rules -------------------------------------------------------------------------------

class AlertEngine:
    """Periodic evaluation. `workers` returns the running camera workers; `pending_events`
    returns {organization_id: count} of events waiting in the recorder's retry queue."""

    def __init__(
        self,
        workers: Callable[[], Iterable] = lambda: [],
        pending_events: Callable[[], Dict[int, int]] = lambda: {},
        interval_seconds: Optional[float] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.workers = workers
        self.pending_events = pending_events
        self.interval = interval_seconds or settings.ALERT_EVAL_INTERVAL_SECONDS
        self.clock = clock
        self._degraded_since: Dict[str, float] = {}
        self._detect_error_since: Dict[str, float] = {}
        self._pending_since: Dict[int, float] = {}
        self._last_hourly: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="alert-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.run_once()

    def run_once(self) -> None:
        if not settings.ALERTS_ENABLED:
            return
        for step in (self.check_camera_offline, self.check_camera_quality, self.check_processing, self.run_hourly_jobs, self.head_guard_tick):
            try:
                step()
            except SQLAlchemyError:
                logger.exception("Alert engine step %s failed (database)", step.__name__)
            except Exception:
                logger.exception("Alert engine step %s failed", step.__name__)

    # camera_offline -------------------------------------------------------------------------
    def check_camera_offline(self) -> None:
        now = utcnow()
        with session_scope() as db:
            open_rows = db.execute(
                select(CameraIncident, Camera)
                .join(Camera, Camera.id == CameraIncident.camera_id)
                .where(CameraIncident.ended_at.is_(None))
            ).all()
            open_cams = {cam.id for _, cam in open_rows}
            # Clear alerts for cameras that recovered (or were deliberately stopped).
            from models.entities import Alert, OPEN_ALERT_STATUSES

            stale = db.execute(select(Alert.organization_id, Alert.dedup_key).where(
                Alert.rule_type == "camera_offline", Alert.status.in_(OPEN_ALERT_STATUSES)
            )).all()
            for org_id, key in stale:
                if key.split(":", 1)[1] not in open_cams:
                    auto_resolve(db, org_id, key, "Camera delivered video again; resolved automatically.")
            todo = [(i.started_at, i.kind, i.message, cam.id, cam.name, cam.organization_id, cam.location_id) for i, cam in open_rows]
        for started_at, kind, message, cam_id, cam_name, org_id, loc_id in todo:
            rule = rules_for(org_id)["camera_offline"]
            if not rule.enabled or (now - started_at).total_seconds() < int(rule.params["grace_seconds"]):
                continue
            minutes = int((now - started_at).total_seconds() // 60)
            _emit(_draft(
                rule, org_id, f"camera_offline:{cam_id}",
                f"{cam_name} has not delivered video for {minutes} minute(s) ({kind.replace('_', ' ')}: {message or 'no detail'}). "
                "Entries and exits at this camera are not being counted.",
                started_at, location_id=loc_id, camera_id=cam_id,
                metrics={"incident": kind, "offline_minutes": minutes},
            ), rule)

    # camera_quality ------------------------------------------------------------------------
    def check_camera_quality(self) -> None:
        now = self.clock()
        seen = set()
        for worker in list(self.workers()):
            spec = worker.spec
            if spec.organization_id is None:
                continue
            seen.add(spec.id)
            rule = rules_for(spec.organization_id)["camera_quality"]
            q = worker.quality if worker.status == "live" else None
            p = rule.params
            problems = []
            if q:
                if q["brightness"] < p["min_brightness"]:
                    problems.append(f"very dark (brightness {q['brightness']:.0f} < {p['min_brightness']:.0f})")
                if q["contrast"] < p["min_contrast"]:
                    problems.append(f"almost uniform, possibly covered or obstructed (contrast {q['contrast']:.1f} < {p['min_contrast']:.1f})")
                if q["sharpness"] < p["min_sharpness"]:
                    problems.append(f"blurred (sharpness {q['sharpness']:.1f} < {p['min_sharpness']:.1f})")
            key = f"camera_quality:{spec.id}"
            if not problems:
                if self._degraded_since.pop(spec.id, None) is not None:
                    with session_scope() as db:
                        auto_resolve(db, spec.organization_id, key, "Image quality returned to normal; resolved automatically.")
                continue
            since = self._degraded_since.setdefault(spec.id, now)
            if not rule.enabled or now - since < int(p["sustain_seconds"]):
                continue
            _emit(_draft(
                rule, spec.organization_id, key,
                f"The image from {spec.name} has been {', '.join(problems)} for {int(now - since)} seconds.",
                datetime.fromtimestamp(since, tz=timezone.utc), location_id=spec.location_id, camera_id=spec.id,
                metrics={**q, "degraded_seconds": int(now - since)},
            ), rule)
        for cam_id in [c for c in self._degraded_since if c not in seen]:
            del self._degraded_since[cam_id]

    # processing_error ----------------------------------------------------------------------
    def check_processing(self) -> None:
        now = self.clock()
        seen = set()
        for worker in list(self.workers()):
            spec = worker.spec
            if spec.organization_id is None:
                continue
            seen.add(spec.id)
            rule = rules_for(spec.organization_id)["processing_error"]
            key = f"processing_error:detector:{spec.id}"
            if worker.status == "live" and worker.detection_status == "error":
                since = self._detect_error_since.setdefault(spec.id, now)
                if rule.enabled and now - since >= int(rule.params["sustain_seconds"]):
                    _emit(_draft(
                        rule, spec.organization_id, key,
                        f"Person detection is failing on {spec.name}: {worker.detection_message}. Entries and exits are not being counted.",
                        datetime.fromtimestamp(since, tz=timezone.utc), location_id=spec.location_id, camera_id=spec.id,
                        metrics={"detection_status": worker.detection_status, "failing_seconds": int(now - since)},
                    ), rule)
            elif self._detect_error_since.pop(spec.id, None) is not None:
                with session_scope() as db:
                    auto_resolve(db, spec.organization_id, key, "Detection recovered; resolved automatically.")
        for cam_id in [c for c in self._detect_error_since if c not in seen]:
            del self._detect_error_since[cam_id]

        pending = self.pending_events()
        for org_id in set(pending) | set(self._pending_since):
            rule = rules_for(org_id)["processing_error"]
            key = "processing_error:event_writes"
            if pending.get(org_id):
                since = self._pending_since.setdefault(org_id, now)
                if rule.enabled and now - since >= int(rule.params["sustain_seconds"]):
                    _emit(_draft(
                        rule, org_id, key,
                        f"{pending[org_id]} recorded event(s) are waiting to be written to the database "
                        f"(for {int(now - since)} seconds). They are retried automatically; check database health.",
                        datetime.fromtimestamp(since, tz=timezone.utc), title="Delayed event delivery",
                        metrics={"pending_events": pending[org_id]},
                    ), rule)
            elif self._pending_since.pop(org_id, None) is not None:
                with session_scope() as db:
                    auto_resolve(db, org_id, key, "Pending events were written; resolved automatically.")

        if settings.IS_EDGE:
            self._check_sync_delay()

    def _check_sync_delay(self) -> None:
        with session_scope() as db:
            rows = db.execute(
                select(SyncOutbox.organization_id, func.min(SyncOutbox.created_at), func.count())
                .where(SyncOutbox.status == "pending").group_by(SyncOutbox.organization_id)
            ).all()
        for org_id, oldest, n in rows:
            rule = rules_for(org_id)["processing_error"]
            delay = (utcnow() - oldest).total_seconds() / 60
            if rule.enabled and delay >= int(rule.params["max_sync_delay_minutes"]):
                _emit(_draft(
                    rule, org_id, "processing_error:sync",
                    f"{n} event(s) have not reached the cloud dashboard for {int(delay)} minutes. Local recording continues; "
                    "check the internet connection and SYNC_URL.",
                    oldest, title="Cloud synchronisation delayed", metrics={"pending": n, "oldest_minutes": int(delay)},
                ), rule)

    # head guard: auto-resolve quiet incidents, daily briefing ---------------------------------
    def head_guard_tick(self) -> None:
        from services.head_guard import tick

        tick()

    # hourly jobs: ML inference and scheduled reports ---------------------------------------------
    def run_hourly_jobs(self) -> None:
        hour = utcnow().strftime("%Y-%m-%dT%H")
        if hour == self._last_hourly:
            return
        self._last_hourly = hour
        from services.ml_anomaly import run_inference_all
        from services.report_schedules import run_due_schedules

        if settings.ML_ANOMALY_ENABLED:
            for org_id, findings in run_inference_all().items():
                rule = rules_for(org_id)["ml_anomaly"]
                if not rule.enabled:
                    continue
                for f in findings:
                    _emit(_draft(
                        rule, org_id, f"ml_anomaly:{f['location_id']}:{f['hour_start']}", f["reason"],
                        datetime.fromisoformat(f["hour_start"]), location_id=f["location_id"],
                        model_score=f["score"], metrics=f["metrics"],
                    ), rule)
        run_due_schedules()
