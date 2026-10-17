"""
Guards: every camera is a guard standing at a post with a set of duties.

A guard only reports what its duties cover. For example, a corridor guard watches for fights and
loitering but does not log gate entries. Reports are ordinary alerts. The head guard
(services/head_guard.py) groups related reports into incidents and decides what to escalate to the owner.

- POSTS describe typical places in a PG / hostel / home / office and their default duties.
- DUTIES map to alert rules. A rule raised on a camera is kept only when one of that camera's duties
  covers it. Camera-health and system rules (camera offline, obstructed view, processing errors,
  ML patterns) are always kept: a guard always reports that it cannot see.
- A camera without a post ("general watch") keeps every duty, so existing setups behave as before.
- The fight duty also decides whether the video anomaly model analyses the camera, which saves
  CPU on large (16-camera) installations.
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import session_scope
from models.entities import Camera


@dataclass(frozen=True)
class Duty:
    key: str
    label: str
    description: str
    rules: Tuple[str, ...]
    # What the guard needs on its camera for this duty to work (checked by the head guard).
    needs: str = ""  # "" | "line" | "zone" | "restricted_zone" | "video_model" | "hours"


DUTIES: Dict[str, Duty] = {
    d.key: d
    for d in (
        Duty("gate_log", "Gate entry / exit log",
             "Counts every entry and exit at the counting line and flags someone crossing back and forth.",
             ("repeated_crossings",), needs="line"),
        Duty("curfew", "Curfew / after-hours watch",
             "Reports entries and exits outside the location's opening hours (for example the PG gate curfew).",
             ("after_hours",), needs="hours"),
        Duty("crowding", "Crowding & headcount",
             "Reports unusual traffic at the line and occupancy above the location's capacity.",
             ("traffic_frequency", "occupancy"), needs="line"),
        Duty("fight", "Fight / altercation watch",
             "Runs the video anomaly model and reports possible fights or violent movement between people.",
             ("video_anomaly_model",), needs="video_model"),
        Duty("restricted", "Restricted area watch",
             "Reports anyone inside a zone marked restricted (terrace, store room, office, girls' / boys' wing).",
             ("restricted_zone",), needs="restricted_zone"),
        Duty("loitering", "Loitering watch",
             "Reports someone staying in a monitored zone longer than its dwell time.",
             ("zone_dwell",), needs="zone"),
    )
}

# Always reported regardless of duties.
ALWAYS_RULES = frozenset({"camera_offline", "camera_quality", "processing_error", "ml_anomaly"})


@dataclass(frozen=True)
class Post:
    key: str
    label: str
    description: str
    duties: Tuple[str, ...]


POSTS: Dict[str, Post] = {
    p.key: p
    for p in (
        Post("main_gate", "Main gate", "The gate or main door everyone uses. Logs entries / exits and enforces the curfew.",
             ("gate_log", "curfew", "crowding", "fight")),
        Post("entrance", "Building entrance / reception", "Reception, lobby door or a floor entrance.",
             ("gate_log", "curfew", "fight")),
        Post("corridor", "Corridor / staircase", "Hallways and stairs between rooms, where arguments often start.",
             ("fight", "loitering")),
        Post("common_area", "Common room / mess / lobby", "TV room, dining hall, study area, lobby.",
             ("fight", "crowding", "loitering")),
        Post("restricted", "Restricted area", "Terrace, roof, store room, kitchen, office or a wing others must not enter.",
             ("restricted", "loitering")),
        Post("perimeter", "Perimeter / parking", "Boundary wall, parking, back side of the building.",
             ("restricted", "loitering", "fight")),
        Post("general", "General watch", "Watches for everything; use when no other post fits.",
             tuple(DUTIES)),
    )
}

DEFAULT_POST = "general"
_CACHE_SECONDS = 15.0
_cache: Dict[int, Tuple[float, Dict[str, FrozenSet[str]]]] = {}
_lock = threading.Lock()


class GuardError(ValueError):
    pass


def duties_of(cam: Camera) -> FrozenSet[str]:
    """Effective duties of a camera's guard."""
    if cam.guard_duties is not None:
        try:
            values = json.loads(cam.guard_duties)
            return frozenset(v for v in values if v in DUTIES)
        except (ValueError, TypeError):
            pass
    post = POSTS.get(cam.guard_post or DEFAULT_POST, POSTS[DEFAULT_POST])
    return frozenset(post.duties)


def post_of(cam: Camera) -> Post:
    return POSTS.get(cam.guard_post or DEFAULT_POST, POSTS[DEFAULT_POST])


def guard_display_name(cam: Camera) -> str:
    return cam.guard_name.strip() if cam.guard_name and cam.guard_name.strip() else f"Guard at {cam.name}"


def rules_for_duties(duties: FrozenSet[str]) -> FrozenSet[str]:
    return frozenset(r for d in duties for r in DUTIES[d].rules) | ALWAYS_RULES


def _org_duties(organization_id: int) -> Dict[str, FrozenSet[str]]:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(organization_id)
        if cached and now - cached[0] < _CACHE_SECONDS:
            return cached[1]
    with session_scope() as db:
        cams = db.scalars(select(Camera).where(Camera.organization_id == organization_id)).all()
        duties = {c.id: duties_of(c) for c in cams}
    with _lock:
        _cache[organization_id] = (now, duties)
    return duties


def invalidate(organization_id: Optional[int] = None) -> None:
    with _lock:
        if organization_id is None:
            _cache.clear()
        else:
            _cache.pop(organization_id, None)


def guard_allows(organization_id: int, camera_id: Optional[str], rule_type: str) -> bool:
    """Whether the guard at camera_id reports rule_type. Location-level alerts (no camera) always pass."""
    if not camera_id or rule_type in ALWAYS_RULES:
        return True
    duties = _org_duties(organization_id).get(camera_id)
    if duties is None:  # unknown camera (e.g. created moments ago): do not drop the report
        return True
    return rule_type in rules_for_duties(duties)


def watches_fights(cam: Camera) -> bool:
    return "fight" in duties_of(cam)


def assign(db: Session, cam: Camera, guard_name: Optional[str], post: Optional[str], duties: Optional[List[str]],
           reset_duties: bool = False) -> None:
    """Validate and apply a guard assignment. Caller commits and calls invalidate()."""
    if guard_name is not None:
        name = guard_name.strip()
        if len(name) > 60:
            raise GuardError("Guard names are at most 60 characters.")
        cam.guard_name = name
    if post is not None:
        if post not in POSTS:
            raise GuardError("Unknown post.")
        cam.guard_post = post
    if reset_duties:
        cam.guard_duties = None
    elif duties is not None:
        unknown = [d for d in duties if d not in DUTIES]
        if unknown:
            raise GuardError(f"Unknown duties: {', '.join(unknown)}")
        if not duties:
            raise GuardError("A guard needs at least one duty. Disable the camera instead to take it off duty.")
        # Store the post's default as null so later changes to the post defaults apply.
        chosen = sorted(set(duties))
        default = sorted(POSTS[cam.guard_post or DEFAULT_POST].duties)
        cam.guard_duties = None if chosen == default else json.dumps(chosen)


def catalogue() -> dict:
    return {
        "posts": [{"key": p.key, "label": p.label, "description": p.description, "duties": list(p.duties)} for p in POSTS.values()],
        "duties": [{"key": d.key, "label": d.label, "description": d.description, "needs": d.needs} for d in DUTIES.values()],
    }
