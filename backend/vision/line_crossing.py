"""
Entrance-line crossing logic.

Ported from the existing entrance counter (viahind-person-counter/person_counter.py: EntryLine,
signed distance to an oriented line, anchor point, track timeout) and extended with:

- exit events (crossing in the opposite direction),
- a hysteresis band so that jitter around the line cannot produce events,
- a minimum number of consecutive frames on the new side before a crossing is accepted,
- a geometric check that the crossing went *through* the configured segment,
- per-track cooldown; a reversal inside the cooldown becomes an "uncertain" event,
- spatial duplicate suppression for two tracks on the same person,
- "uncertain" events for tracks lost while half-way across the line.

A detection appearing in a frame never creates an event on its own: a track must first be
confirmed on one side of the line and then confirmed on the other side.

This module is pure Python/numpy and has no camera, model or database dependencies.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

Box = Tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels

OUTSIDE = -1
INSIDE = 1


@dataclass(frozen=True)
class Detection:
    track_id: Optional[int]
    box: Box
    confidence: float


@dataclass(frozen=True)
class LineConfig:
    """Entrance line in normalised coordinates (0..1) plus which side is "inside"."""

    x1: float
    y1: float
    x2: float
    y2: float
    # +1: inside is on the left-hand normal of (x1,y1)->(x2,y2) in image coordinates; -1: right.
    entry_side: int = 1


@dataclass(frozen=True)
class CrossingParams:
    min_confidence: float = 0.45
    cooldown_seconds: float = 3.0
    track_timeout_seconds: float = 4.0
    min_track_hits: int = 3
    min_side_frames: int = 2
    band: float = 0.03  # fraction of min(frame width, height)
    anchor: str = "bottom"  # "bottom" (feet) or "center"
    segment_margin: float = 0.05  # tolerance beyond the line ends, as a fraction of its length
    duplicate_window_seconds: float = 1.5
    duplicate_iou: float = 0.5


@dataclass(frozen=True)
class CrossingEvent:
    event_type: str  # "entry" | "exit" | "uncertain"
    track_id: int
    occurred_at: float
    confidence: float
    box: Box
    reason: Optional[str] = None


@dataclass
class TrackState:
    track_id: int
    first_seen: float
    last_seen: float
    hits: int = 0
    side: Optional[int] = None
    pending_side: Optional[int] = None
    pending_count: int = 0
    side_anchor: Optional[Tuple[float, float]] = None
    last_anchor: Optional[Tuple[float, float]] = None
    last_distance: Optional[float] = None
    last_box: Optional[Box] = None
    last_event_type: Optional[str] = None
    last_event_at: Optional[float] = None
    confidences: Deque[float] = field(default_factory=lambda: deque(maxlen=10))

    @property
    def mean_confidence(self) -> float:
        return float(sum(self.confidences) / len(self.confidences)) if self.confidences else 0.0


def anchor_of(box: Box, mode: str) -> Tuple[float, float]:
    x1, y1, x2, y2 = box
    if mode == "bottom":
        return ((x1 + x2) / 2.0, y2)
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class EntranceGeometry:
    """The entrance line in pixel space for a given frame size."""

    def __init__(self, line: LineConfig, width: int, height: int, band: float):
        self.a = np.array([line.x1 * width, line.y1 * height], dtype=float)
        self.b = np.array([line.x2 * width, line.y2 * height], dtype=float)
        vec = self.b - self.a
        self.length_sq = float(vec @ vec)
        if self.length_sq < 1.0:
            raise ValueError("Entrance line endpoints must be different points.")
        normal = np.array([-vec[1], vec[0]]) / np.sqrt(self.length_sq)
        self.normal = normal * (1 if line.entry_side >= 0 else -1)
        self.band_px = max(1.0, band * min(width, height))

    def signed_distance(self, point: Sequence[float]) -> float:
        """Negative = outside, positive = inside."""
        return float((np.asarray(point, dtype=float) - self.a) @ self.normal)

    def classify(self, distance: float) -> int:
        if distance > self.band_px:
            return INSIDE
        if distance < -self.band_px:
            return OUTSIDE
        return 0

    def passes_through_segment(self, p: Sequence[float], q: Sequence[float], margin: float) -> bool:
        """True if the path p->q crosses the line within the segment (plus a margin)."""
        dp, dq = self.signed_distance(p), self.signed_distance(q)
        if dp == dq or (dp > 0) == (dq > 0):
            return False
        s = dp / (dp - dq)
        x = np.asarray(p, dtype=float) + s * (np.asarray(q, dtype=float) - np.asarray(p, dtype=float))
        u = float((x - self.a) @ (self.b - self.a)) / self.length_sq
        return -margin <= u <= 1.0 + margin


class LineCrossingCounter:
    """Turns per-frame tracked detections into entry / exit / uncertain events."""

    def __init__(self, line: Optional[LineConfig], params: CrossingParams):
        self.line = line
        self.params = params
        self.tracks: Dict[int, TrackState] = {}
        self._geometry: Optional[EntranceGeometry] = None
        self._frame_size: Optional[Tuple[int, int]] = None
        self._recent_events: Deque[CrossingEvent] = deque(maxlen=32)

    # -- configuration -------------------------------------------------------------------
    def set_line(self, line: Optional[LineConfig]) -> None:
        """Changing the line invalidates every track's side, so all tracks start over."""
        self.line = line
        self._geometry = None
        self.tracks.clear()

    def set_params(self, params: CrossingParams) -> None:
        if params.band != self.params.band:
            self._geometry = None
        self.params = params

    def reset(self) -> int:
        """Drop all tracks (e.g. after a camera disconnection). Returns tracks that were mid-crossing."""
        mid = sum(1 for t in self.tracks.values() if self._is_mid_crossing(t))
        self.tracks.clear()
        return mid

    # -- processing ----------------------------------------------------------------------
    def _geometry_for(self, width: int, height: int) -> Optional[EntranceGeometry]:
        if self.line is None:
            return None
        if self._geometry is None or self._frame_size != (width, height):
            self._geometry = EntranceGeometry(self.line, width, height, self.params.band)
            self._frame_size = (width, height)
        return self._geometry

    def update(self, detections: Sequence[Detection], now: float, frame_size: Tuple[int, int]) -> List[CrossingEvent]:
        geometry = self._geometry_for(*frame_size)
        events: List[CrossingEvent] = []
        p = self.params

        for det in detections:
            if det.track_id is None or det.confidence < p.min_confidence:
                continue  # untracked or weak detections are shown but never counted
            st = self.tracks.get(det.track_id)
            if st is None:
                st = TrackState(track_id=det.track_id, first_seen=now, last_seen=now)
                self.tracks[det.track_id] = st
            st.hits += 1
            st.last_seen = now
            st.last_box = det.box
            st.confidences.append(det.confidence)
            if geometry is None:
                continue

            anchor = anchor_of(det.box, p.anchor)
            distance = geometry.signed_distance(anchor)
            observed = geometry.classify(distance)
            st.last_anchor = anchor
            st.last_distance = distance

            if observed == 0:
                continue  # inside the hysteresis band: no decision either way
            if st.side is None:
                self._advance_pending(st, observed)
                if st.pending_count >= p.min_side_frames:
                    st.side, st.side_anchor = observed, anchor
                    st.pending_side, st.pending_count = None, 0
                continue
            if observed == st.side:
                st.side_anchor = anchor
                st.pending_side, st.pending_count = None, 0
                continue

            self._advance_pending(st, observed)
            if st.pending_count < p.min_side_frames:
                continue
            through = st.side_anchor is not None and geometry.passes_through_segment(
                st.side_anchor, anchor, p.segment_margin
            )
            st.side, st.side_anchor = observed, anchor
            st.pending_side, st.pending_count = None, 0
            if not through or st.hits < p.min_track_hits:
                continue  # walked around the end of the line, or too short-lived to trust
            event = self._make_event(st, "entry" if observed == INSIDE else "exit", now)
            if event is not None:
                events.append(event)

        events.extend(self.expire(now))
        return events

    def expire(self, now: float) -> List[CrossingEvent]:
        """Remove tracks not seen within the timeout; flag those lost half-way across the line."""
        events: List[CrossingEvent] = []
        stale = [t for t in self.tracks.values() if now - t.last_seen > self.params.track_timeout_seconds]
        for st in stale:
            del self.tracks[st.track_id]
            if self._is_mid_crossing(st) and st.hits >= self.params.min_track_hits:
                event = self._make_event(st, "uncertain", st.last_seen, reason="lost_while_crossing")
                if event is not None:
                    events.append(event)
        return events

    # -- helpers -------------------------------------------------------------------------
    @staticmethod
    def _advance_pending(st: TrackState, observed: int) -> None:
        if st.pending_side == observed:
            st.pending_count += 1
        else:
            st.pending_side, st.pending_count = observed, 1

    def _is_mid_crossing(self, st: TrackState) -> bool:
        """Confirmed on one side, last seen past the centre line toward the other side."""
        if st.side is None or st.last_distance is None or self._geometry is None:
            return False
        if st.last_distance * st.side >= 0:
            return False
        return st.side_anchor is not None and st.last_anchor is not None and self._geometry.passes_through_segment(
            st.side_anchor, st.last_anchor, self.params.segment_margin
        )

    def _make_event(self, st: TrackState, event_type: str, now: float, reason: Optional[str] = None) -> Optional[CrossingEvent]:
        p = self.params
        if (
            event_type != "uncertain"
            and st.last_event_at is not None
            and now - st.last_event_at < p.cooldown_seconds
            and st.last_event_type != event_type
        ):
            # Reversed direction straight after an event: do not guess, ask an operator.
            event_type, reason = "uncertain", "direction_reversal"

        box = st.last_box or (0.0, 0.0, 0.0, 0.0)
        for prev in self._recent_events:
            if (
                prev.track_id != st.track_id
                and prev.event_type == event_type
                and now - prev.occurred_at < p.duplicate_window_seconds
                and iou(prev.box, box) >= p.duplicate_iou
            ):
                return None  # a second track on the same person crossing at the same moment

        st.last_event_type, st.last_event_at = event_type, now
        event = CrossingEvent(
            event_type=event_type,
            track_id=st.track_id,
            occurred_at=now,
            confidence=round(st.mean_confidence, 3),
            box=box,
            reason=reason,
        )
        self._recent_events.append(event)
        return event

    def overlay_tracks(self) -> List[dict]:
        """Current track positions for the live view overlay."""
        out = []
        for st in self.tracks.values():
            if st.last_box is None:
                continue
            out.append(
                {
                    "track_id": st.track_id,
                    "box": [round(v, 1) for v in st.last_box],
                    "side": {INSIDE: "inside", OUTSIDE: "outside"}.get(st.side, "unknown"),
                    "last_event": st.last_event_type,
                }
            )
        return out
