"""
Event-level anomaly detection baseline (Isolation Forest).

Stage 2/3 of the anomaly strategy: rules first (services/alert_rules.py), then this statistical
baseline over structured features built from real stored events. It answers one question:
"is this hour of activity at this location unusual compared with its own history?"

Feature schema v1 (one row per location per local hour):
    entries, exits, uncertain, net_flow          counts from non-rejected, non-demo events
    hour_sin, hour_cos, dow_sin, dow_cos         time of day / day of week (cyclic encoding)
Counts are standardised with the training mean and standard deviation stored in the model
metadata, so inference uses exactly the training preprocessing.

Training data rules:
- only real events (is_demo = False); never fabricated data,
- only hours between the location's first and last event in the window,
- hours overlapping a camera interruption at that location are excluded (no coverage),
- at least ML_MIN_TRAINING_HOURS usable hours spread over ML_MIN_TRAINING_DAYS days and 50 events;
  otherwise the run is recorded as "insufficient_data" and no model is produced.

Artifacts are written to MODEL_DIR/org_<id>/ with their SHA-256 recorded in the database; a model is
loaded only from inside MODEL_DIR and only if the file hash matches. (joblib files are pickles: never
copy model files from untrusted sources into MODEL_DIR.)

A model score is a statistical outlier measure. It never proves misconduct and must not trigger
punitive action; findings become low-severity alerts for human review.
"""

import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db import session_scope, utcnow
from models.entities import Alert, AnomalyModel, Camera, CameraIncident, DetectionEvent, Location, Organization
from services.site_settings import get_site_settings, site_zone

logger = logging.getLogger("viahind.ml")

FEATURE_SCHEMA_VERSION = 1
COUNT_FEATURES = ("entries", "exits", "uncertain", "net_flow")
TIME_FEATURES = ("hour_sin", "hour_cos", "dow_sin", "dow_cos")
FEATURES = COUNT_FEATURES + TIME_FEATURES
ALGORITHM = "isolation_forest"
MIN_EVENTS = 50
MAX_TRAINING_DAYS = 180


class MLUnavailable(RuntimeError):
    pass


def _sklearn():
    try:
        import joblib  # noqa: F401
        import numpy as np  # noqa: F401
        from sklearn.ensemble import IsolationForest  # noqa: F401
    except Exception as exc:  # ImportError, or a broken binary install
        raise MLUnavailable(f"scikit-learn is not available ({type(exc).__name__}). Install scikit-learn and joblib.") from exc
    import joblib
    import numpy as np
    from sklearn.ensemble import IsolationForest

    return joblib, np, IsolationForest


def ml_available() -> Tuple[bool, str]:
    try:
        _sklearn()
        return True, "scikit-learn available."
    except MLUnavailable as exc:
        return False, str(exc)


# -- features ---------------------------------------------------------------------------------------

def time_features(local: datetime) -> Dict[str, float]:
    h = local.hour / 24.0 * 2 * math.pi
    d = local.weekday() / 7.0 * 2 * math.pi
    return {"hour_sin": math.sin(h), "hour_cos": math.cos(h), "dow_sin": math.sin(d), "dow_cos": math.cos(d)}


def _incident_spans(db: Session, organization_id: int, location_id: int, start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    rows = db.execute(
        select(CameraIncident.started_at, CameraIncident.ended_at)
        .join(Camera, Camera.id == CameraIncident.camera_id)
        .where(CameraIncident.organization_id == organization_id, Camera.location_id == location_id,
               CameraIncident.started_at < end)
    ).all()
    now = utcnow()
    return [(s, e or now) for s, e in rows if (e or now) > start]


def hourly_rows(db: Session, organization_id: int, location_id: int, start: datetime, end: datetime, tz) -> List[dict]:
    """Feature rows for each local hour in [start, end) that had coverage."""
    counts: Dict[datetime, Dict[str, int]] = defaultdict(lambda: {"entry": 0, "exit": 0, "uncertain": 0})
    first = last = None
    for occurred_at, kind in db.execute(
        select(DetectionEvent.occurred_at, DetectionEvent.event_type).where(
            DetectionEvent.organization_id == organization_id, DetectionEvent.location_id == location_id,
            DetectionEvent.occurred_at >= start, DetectionEvent.occurred_at < end,
            DetectionEvent.review_status != "rejected", DetectionEvent.is_demo.is_(False),
        )
    ):
        hour = occurred_at.astimezone(tz).replace(minute=0, second=0, microsecond=0)
        counts[hour][kind] = counts[hour].get(kind, 0) + 1
        first = hour if first is None or hour < first else first
        last = hour if last is None or hour > last else last
    if first is None:
        return []
    gaps = _incident_spans(db, organization_id, location_id, start, end)
    rows = []
    hour = first
    while hour <= last:
        h_start = hour.astimezone(timezone.utc)
        h_end = (hour + timedelta(hours=1)).astimezone(timezone.utc)
        if not any(s < h_end and e > h_start for s, e in gaps):
            c = counts.get(hour, {"entry": 0, "exit": 0, "uncertain": 0})
            row = {"hour_start": h_start, "local_hour": hour.hour, "entries": c["entry"], "exits": c["exit"],
                   "uncertain": c["uncertain"], "net_flow": c["entry"] - c["exit"]}
            row.update(time_features(hour))
            rows.append(row)
        hour = (hour + timedelta(hours=1)).astimezone(tz).replace(minute=0, second=0, microsecond=0)
    return rows


def validate_row(row: dict) -> Optional[str]:
    for name in FEATURES:
        v = row.get(name)
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            return f"feature '{name}' is missing or not a finite number"
    for name in ("entries", "exits", "uncertain"):
        if row[name] < 0:
            return f"feature '{name}' is negative"
    return None


def standardise(row: dict, means: Dict[str, float], stds: Dict[str, float]) -> List[float]:
    out = []
    for name in FEATURES:
        if name in COUNT_FEATURES:
            out.append((row[name] - means[name]) / (stds[name] or 1.0))
        else:
            out.append(float(row[name]))
    return out


# -- artifacts ----------------------------------------------------------------------------------------

def _model_root() -> Path:
    root = Path(settings.MODEL_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_artifact(model: AnomalyModel):
    """Load a registered artifact after path and integrity checks."""
    joblib, _np, _IF = _sklearn()
    if not model.artifact_path or not model.artifact_sha256:
        raise ValueError("The model has no artifact.")
    root = _model_root()
    path = (root / model.artifact_path).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("The model artifact is missing or outside MODEL_DIR.")
    if _sha256(path) != model.artifact_sha256:
        raise ValueError("The model artifact failed its integrity check (hash mismatch); retrain the model.")
    return joblib.load(path)


# -- training -----------------------------------------------------------------------------------------

def train_model(organization_id: int, trained_by: Optional[str] = None, days: int = 60, contamination: float = 0.01) -> dict:
    """Train (or record why training was not possible) and activate the new model on success."""
    days = max(7, min(int(days), MAX_TRAINING_DAYS))
    if not 0.001 <= contamination <= 0.1:
        raise ValueError("Contamination must be between 0.001 and 0.1.")
    version = utcnow().strftime("%Y%m%d%H%M%S")
    with session_scope() as db:
        tz = site_zone(get_site_settings(db, organization_id))
        end = utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        rows: List[dict] = []
        per_location: Dict[int, int] = {}
        for loc in db.scalars(select(Location).where(Location.organization_id == organization_id)):
            loc_rows = hourly_rows(db, organization_id, loc.id, start, end, tz)
            per_location[loc.id] = len(loc_rows)
            rows += loc_rows
        rows = [r for r in rows if validate_row(r) is None]
        n_events = sum(r["entries"] + r["exits"] + r["uncertain"] for r in rows)
        n_days = len({r["hour_start"].astimezone(tz).date() for r in rows})
        quality = {"usable_hours": len(rows), "days_covered": n_days, "events": n_events, "hours_per_location": per_location,
                   "window_days": days}

        problems = []
        if len(rows) < settings.ML_MIN_TRAINING_HOURS:
            problems.append(f"{len(rows)} usable hours (need {settings.ML_MIN_TRAINING_HOURS})")
        if n_days < settings.ML_MIN_TRAINING_DAYS:
            problems.append(f"{n_days} days with data (need {settings.ML_MIN_TRAINING_DAYS})")
        if n_events < MIN_EVENTS:
            problems.append(f"{n_events} events (need {MIN_EVENTS})")
        record = AnomalyModel(
            organization_id=organization_id, version=version, algorithm=ALGORITHM,
            feature_schema_version=FEATURE_SCHEMA_VERSION, n_samples=len(rows), trained_by=trained_by, trained_at=utcnow(),
        )
        if problems:
            record.status = "insufficient_data"
            record.message = "Not enough real data to train yet: " + "; ".join(problems) + ". Rules-based alerts continue to work."
            record.metadata_json = json.dumps({"data_quality": quality})
            db.add(record)
            db.flush()
            return serialize_model(record)

    try:
        joblib, np, IsolationForest = _sklearn()
    except MLUnavailable as exc:
        with session_scope() as db:
            record.status, record.message = "failed", str(exc)
            record.metadata_json = json.dumps({"data_quality": quality})
            db.add(record)
            db.flush()
            return serialize_model(record)

    means = {f: float(np.mean([r[f] for r in rows])) for f in COUNT_FEATURES}
    stds = {f: float(np.std([r[f] for r in rows])) or 1.0 for f in COUNT_FEATURES}
    X = np.array([standardise(r, means, stds) for r in rows], dtype=float)
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
    model.fit(X)
    scores = model.decision_function(X)
    threshold = 0.0  # decision_function < 0 means the model calls the sample an outlier
    flagged = int((scores < threshold).sum())

    # Typical activity by local hour of day, for human-readable explanations.
    profile: Dict[int, Dict[str, float]] = {}
    for h in range(24):
        hr = [r for r in rows if r["local_hour"] == h]
        if hr:
            profile[h] = {"entries": round(sum(r["entries"] for r in hr) / len(hr), 2),
                          "exits": round(sum(r["exits"] for r in hr) / len(hr), 2), "samples": len(hr)}

    org_dir = _model_root() / f"org_{organization_id}"
    org_dir.mkdir(parents=True, exist_ok=True)
    rel = f"org_{organization_id}/{ALGORITHM}_{version}.joblib"
    joblib.dump(model, _model_root() / rel)
    digest = _sha256(_model_root() / rel)

    with session_scope() as db:
        for previous in db.scalars(select(AnomalyModel).where(AnomalyModel.organization_id == organization_id, AnomalyModel.active.is_(True))):
            previous.active = False
            previous.status = "retired"
        record.status = "ready"
        record.active = True
        record.artifact_path, record.artifact_sha256 = rel, digest
        record.message = f"Trained on {len(rows)} hours over {n_days} days; {flagged} training hours ({flagged / len(rows):.1%}) score as unusual."
        record.metadata_json = json.dumps({
            "features": list(FEATURES), "means": means, "stds": stds, "threshold": threshold, "contamination": contamination,
            "training_window": {"start": start.isoformat(), "end": end.isoformat()}, "hour_profile": profile,
            "data_quality": quality, "training_flagged_hours": flagged,
        }, sort_keys=True)
        db.add(record)
        db.flush()
        _prune_artifacts(db, organization_id)
        return serialize_model(record)


def _prune_artifacts(db: Session, organization_id: int, keep: int = 3) -> None:
    rows = list(db.scalars(
        select(AnomalyModel).where(AnomalyModel.organization_id == organization_id, AnomalyModel.artifact_path.is_not(None))
        .order_by(AnomalyModel.trained_at.desc())
    ))
    for old in rows[keep:]:
        try:
            path = (_model_root() / old.artifact_path).resolve()
            if _model_root() in path.parents and path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Could not delete old model artifact %s", old.artifact_path)
        old.artifact_path = None
        old.artifact_sha256 = None


# -- inference ----------------------------------------------------------------------------------------

def explain(row: dict, meta: dict) -> Tuple[str, dict]:
    profile = meta.get("hour_profile", {}).get(str(row["local_hour"])) or meta.get("hour_profile", {}).get(row["local_hour"])
    parts = []
    metrics = {k: row[k] for k in COUNT_FEATURES}
    if profile:
        metrics["typical_entries_this_hour"] = profile["entries"]
        metrics["typical_exits_this_hour"] = profile["exits"]
        parts.append(f"{row['entries']} entries and {row['exits']} exits between {row['local_hour']:02d}:00 and "
                     f"{(row['local_hour'] + 1) % 24:02d}:00, compared with about {profile['entries']:g} entries and "
                     f"{profile['exits']:g} exits in that hour in the training data")
    else:
        parts.append(f"{row['entries']} entries and {row['exits']} exits at {row['local_hour']:02d}:00, an hour with no activity in the training data")
    z = {f: (row[f] - meta["means"][f]) / (meta["stds"][f] or 1.0) for f in COUNT_FEATURES}
    top = sorted(z.items(), key=lambda kv: -abs(kv[1]))[:2]
    metrics["largest_deviations"] = {k: round(v, 2) for k, v in top}
    return "; ".join(parts) + ".", metrics


def score_rows(model_record: AnomalyModel, estimator, rows: List[dict]) -> List[dict]:
    import numpy as np

    meta = json.loads(model_record.metadata_json or "{}")
    findings = []
    valid = []
    for r in rows:
        problem = validate_row(r)
        if problem:
            logger.info("Skipping hour %s for anomaly scoring: %s", r.get("hour_start"), problem)
            continue
        valid.append(r)
    if not valid:
        return []
    X = np.array([standardise(r, meta["means"], meta["stds"]) for r in valid], dtype=float)
    scores = estimator.decision_function(X)
    for r, score in zip(valid, scores):
        if score < meta.get("threshold", 0.0):
            text, metrics = explain(r, meta)
            findings.append({
                "hour_start": r["hour_start"].isoformat(), "score": round(float(score), 4), "metrics": metrics,
                "reason": f"Unusual activity pattern: {text} Model score {score:.3f} (threshold {meta.get('threshold', 0.0):.3f}; "
                          f"model {model_record.version}). This is a statistical outlier for review, not evidence of a problem.",
            })
    return findings


def run_inference(organization_id: int, now: Optional[datetime] = None, max_hours: int = 24) -> List[dict]:
    """Score completed hours since the last inference with the active model."""
    now = now or utcnow()
    with session_scope() as db:
        model = db.scalar(select(AnomalyModel).where(AnomalyModel.organization_id == organization_id, AnomalyModel.active.is_(True)))
        if model is None or model.status != "ready":
            return []
        if model.feature_schema_version != FEATURE_SCHEMA_VERSION:
            model.message = "Feature schema changed since training; retrain the model."
            model.status = "failed"
            model.active = False
            return []
        try:
            estimator = load_artifact(model)
        except (ValueError, MLUnavailable) as exc:
            model.message = str(exc)
            model.status = "failed"
            model.active = False
            return []
        tz = site_zone(get_site_settings(db, organization_id))
        end = now.astimezone(tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        start = max(model.last_inference_at or (end - timedelta(hours=1)), end - timedelta(hours=max_hours))
        if start >= end:
            return []
        findings = []
        for loc in db.scalars(select(Location).where(Location.organization_id == organization_id, Location.is_active.is_(True))):
            rows = [r for r in hourly_rows(db, organization_id, loc.id, start, end, tz) if r["hour_start"] >= start]
            for f in score_rows(model, estimator, rows):
                f["location_id"] = loc.id
                f["reason"] = f"{loc.name}: " + f["reason"]
                findings.append(f)
        model.last_inference_at = end
        return findings


def run_inference_all() -> Dict[int, List[dict]]:
    ok, _ = ml_available()
    if not ok:
        return {}
    out: Dict[int, List[dict]] = {}
    with session_scope() as db:
        org_ids = list(db.scalars(select(AnomalyModel.organization_id).where(AnomalyModel.active.is_(True)).distinct()))
    for org_id in org_ids:
        try:
            out[org_id] = run_inference(org_id)
        except Exception:
            logger.exception("Anomaly inference failed for organization %s", org_id)
    return out


# -- status -------------------------------------------------------------------------------------------

def review_feedback(db: Session, organization_id: int) -> dict:
    """How reviewers closed ML alerts: a running estimate of false positives."""
    rows = db.execute(select(Alert.status).where(Alert.organization_id == organization_id, Alert.rule_type == "ml_anomaly")).all()
    counts: Dict[str, int] = defaultdict(int)
    for (status,) in rows:
        counts[status] += 1
    reviewed = counts["resolved"] + counts["dismissed"]
    return {
        "alerts": sum(counts.values()), "open": counts["new"] + counts["acknowledged"], "resolved": counts["resolved"],
        "dismissed": counts["dismissed"],
        "dismissed_rate": round(counts["dismissed"] / reviewed, 3) if reviewed else None,
    }


def serialize_model(row: AnomalyModel) -> dict:
    meta = json.loads(row.metadata_json or "{}")
    return {
        "id": row.id, "version": row.version, "algorithm": row.algorithm, "status": row.status, "active": row.active,
        "feature_schema_version": row.feature_schema_version, "n_samples": row.n_samples, "message": row.message,
        "trained_by": row.trained_by, "trained_at": row.trained_at.isoformat(),
        "last_inference_at": row.last_inference_at.isoformat() if row.last_inference_at else None,
        "features": meta.get("features"), "contamination": meta.get("contamination"), "threshold": meta.get("threshold"),
        "data_quality": meta.get("data_quality"), "training_window": meta.get("training_window"),
        "has_artifact": bool(row.artifact_path),
    }


def model_status(db: Session, organization_id: int) -> dict:
    ok, message = ml_available()
    models = list(db.scalars(select(AnomalyModel).where(AnomalyModel.organization_id == organization_id)
                             .order_by(AnomalyModel.trained_at.desc()).limit(10)))
    active = next((m for m in models if m.active), None)
    return {
        "enabled": settings.ML_ANOMALY_ENABLED, "available": ok, "message": message,
        "requirements": {"min_hours": settings.ML_MIN_TRAINING_HOURS, "min_days": settings.ML_MIN_TRAINING_DAYS, "min_events": MIN_EVENTS},
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "features": list(FEATURES),
        "active": serialize_model(active) if active else None,
        "history": [serialize_model(m) for m in models],
        "review_feedback": review_feedback(db, organization_id),
    }
