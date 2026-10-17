"""
Alert rule catalogue: what each rule detects, its parameters and defaults.

Rules describe *operational* conditions (a camera is offline, a restricted area was entered,
traffic is unusually high). They never infer identity, intent or wrongdoing; every alert carries
the measured values that triggered it and must be reviewed by a person.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import utcnow
from models.entities import ALERT_SEVERITIES, AlertRule


@dataclass(frozen=True)
class Param:
    kind: type  # int | float | bool
    default: object
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    label: str = ""


@dataclass(frozen=True)
class RuleDef:
    rule_type: str
    category: str
    title: str
    description: str
    severity: str
    enabled: bool = True
    cooldown_seconds: int = 900
    params: Dict[str, Param] = field(default_factory=dict)


RULES: Dict[str, RuleDef] = {
    r.rule_type: r
    for r in (
        RuleDef(
            "restricted_zone", "zone", "Restricted zone entry",
            "A tracked person was confirmed inside a zone marked as restricted on a camera.",
            "high",
        ),
        RuleDef(
            "zone_dwell", "zone", "Long presence in a zone",
            "A tracked person stayed in a zone longer than that zone's dwell threshold. "
            "Dwell restarts if the tracker loses the person, so the time shown is a lower bound.",
            "medium",
        ),
        RuleDef(
            "after_hours", "operations", "Activity outside business hours",
            "An entry or exit was recorded outside the location's configured business hours.",
            "medium", cooldown_seconds=1800,
            params={"grace_minutes": Param(int, 15, 0, 240, "Minutes of tolerance before opening / after closing")},
        ),
        RuleDef(
            "traffic_frequency", "traffic", "Unusual entry/exit frequency",
            "More entries plus exits than expected were recorded on one camera within a short window.",
            "low",
            params={
                "window_minutes": Param(int, 10, 1, 240, "Window (minutes)"),
                "max_events": Param(int, 80, 1, 100000, "Maximum entries + exits in the window"),
            },
        ),
        RuleDef(
            "occupancy", "occupancy", "Unexpected occupancy",
            "Estimated occupancy exceeded the location's capacity, or changed by more than the "
            "configured amount within the window.",
            "medium",
            params={
                "window_minutes": Param(int, 15, 1, 240, "Window (minutes)"),
                "max_change": Param(int, 40, 1, 10000, "Maximum net change in the window"),
                "use_capacity": Param(bool, True, label="Alert when the location capacity is exceeded"),
            },
        ),
        RuleDef(
            "repeated_crossings", "movement", "Repeated line crossings",
            "The same tracked person crossed the counting line many times within a short window "
            "(for example pacing at the door, or a tracking fault worth checking).",
            "low",
            params={
                "window_minutes": Param(int, 10, 1, 120, "Window (minutes)"),
                "min_crossings": Param(int, 4, 2, 100, "Crossings by one track in the window"),
            },
        ),
        RuleDef(
            "camera_offline", "camera_health", "Camera stream interrupted",
            "A camera that was monitoring stopped delivering video for longer than the grace period.",
            "high", cooldown_seconds=3600,
            params={"grace_seconds": Param(int, 60, 0, 3600, "Grace period (seconds)")},
        ),
        RuleDef(
            "camera_quality", "camera_health", "Camera view obstructed or degraded",
            "The image stayed very dark, uniform (covered or obstructed) or blurred for a sustained period.",
            "medium", cooldown_seconds=3600,
            params={
                "min_brightness": Param(float, 12.0, 0, 255, "Minimum mean brightness (0-255)"),
                "min_contrast": Param(float, 6.0, 0, 128, "Minimum contrast (standard deviation)"),
                "min_sharpness": Param(float, 4.0, 0, 10000, "Minimum sharpness (Laplacian variance)"),
                "sustain_seconds": Param(int, 120, 10, 3600, "Degradation must last (seconds)"),
            },
        ),
        RuleDef(
            "processing_error", "system", "Processing or delivery problem",
            "Person detection is failing on a live camera, recorded events are waiting to be written "
            "to the database, or events are waiting to be synchronised to the cloud.",
            "high", cooldown_seconds=1800,
            params={
                "sustain_seconds": Param(int, 60, 10, 3600, "Problem must last (seconds)"),
                "max_sync_delay_minutes": Param(int, 30, 1, 1440, "Maximum cloud sync delay (minutes)"),
            },
        ),
        RuleDef(
            "ml_anomaly", "pattern", "Unusual activity pattern",
            "The Isolation Forest baseline scored an hour of activity as unusual compared with this "
            "location's history. A statistical outlier is not evidence of any problem; review the metrics.",
            "low", cooldown_seconds=3600,
        ),
        RuleDef(
            "video_anomaly_model", "video_model", "Video anomaly (altercation / vigorous movement)",
            "The video anomaly detector confirmed a detection over consecutive clips: either the trained "
            "altercation classifier above its threshold, or (without trained weights) vigorous movement between "
            "people in close contact. Outputs can be wrong and always require human verification.",
            "high", cooldown_seconds=600,
        ),
    )
}

CATEGORIES = sorted({r.category for r in RULES.values()})


@dataclass(frozen=True)
class EffectiveRule:
    rule_type: str
    enabled: bool
    severity: str
    cooldown_seconds: int
    params: Dict[str, object]

    @property
    def definition(self) -> RuleDef:
        return RULES[self.rule_type]


def validate_params(rule_type: str, params: dict) -> Dict[str, object]:
    """Merge provided parameters over the defaults, validating type and range."""
    definition = RULES[rule_type]
    result: Dict[str, object] = {name: p.default for name, p in definition.params.items()}
    for name, value in (params or {}).items():
        spec = definition.params.get(name)
        if spec is None:
            raise ValueError(f"Unknown parameter '{name}' for rule {rule_type}.")
        if spec.kind is bool:
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false.")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number.")
            value = spec.kind(value)
            if spec.minimum is not None and value < spec.minimum:
                raise ValueError(f"{name} must be at least {spec.minimum:g}.")
            if spec.maximum is not None and value > spec.maximum:
                raise ValueError(f"{name} must be at most {spec.maximum:g}.")
        result[name] = value
    return result


def effective_rules(db: Session, organization_id: int) -> Dict[str, EffectiveRule]:
    stored = {r.rule_type: r for r in db.scalars(select(AlertRule).where(AlertRule.organization_id == organization_id))}
    out: Dict[str, EffectiveRule] = {}
    for rule_type, definition in RULES.items():
        row = stored.get(rule_type)
        if row is None:
            out[rule_type] = EffectiveRule(rule_type, definition.enabled, definition.severity, definition.cooldown_seconds,
                                           validate_params(rule_type, {}))
            continue
        try:
            params = validate_params(rule_type, json.loads(row.params or "{}"))
        except (ValueError, json.JSONDecodeError):
            params = validate_params(rule_type, {})
        severity = row.severity if row.severity in ALERT_SEVERITIES else definition.severity
        out[rule_type] = EffectiveRule(rule_type, row.enabled, severity, row.cooldown_seconds, params)
    return out


def save_rule(db: Session, organization_id: int, rule_type: str, enabled: Optional[bool], severity: Optional[str],
              cooldown_seconds: Optional[int], params: Optional[dict]) -> AlertRule:
    if rule_type not in RULES:
        raise ValueError("Unknown rule.")
    definition = RULES[rule_type]
    row = db.scalar(select(AlertRule).where(AlertRule.organization_id == organization_id, AlertRule.rule_type == rule_type))
    if row is None:
        row = AlertRule(organization_id=organization_id, rule_type=rule_type, enabled=definition.enabled,
                        severity=definition.severity, cooldown_seconds=definition.cooldown_seconds, params="{}")
        db.add(row)
    if enabled is not None:
        row.enabled = enabled
    if severity is not None:
        if severity not in ALERT_SEVERITIES:
            raise ValueError("Unknown severity.")
        row.severity = severity
    if cooldown_seconds is not None:
        if not 0 <= cooldown_seconds <= 86400:
            raise ValueError("Cooldown must be between 0 and 86400 seconds.")
        row.cooldown_seconds = cooldown_seconds
    if params is not None:
        current = json.loads(row.params or "{}")
        current.update(params)
        row.params = json.dumps(validate_params(rule_type, current), sort_keys=True)
    row.updated_at = utcnow()
    db.flush()
    return row


def serialize_rules(db: Session, organization_id: int) -> list:
    rules = effective_rules(db, organization_id)
    out = []
    for rule_type, rule in rules.items():
        d = RULES[rule_type]
        out.append({
            "rule_type": rule_type,
            "title": d.title,
            "description": d.description,
            "category": d.category,
            "enabled": rule.enabled,
            "severity": rule.severity,
            "cooldown_seconds": rule.cooldown_seconds,
            "params": rule.params,
            "param_specs": {
                name: {"type": p.kind.__name__, "default": p.default, "min": p.minimum, "max": p.maximum, "label": p.label}
                for name, p in d.params.items()
            },
        })
    return out
