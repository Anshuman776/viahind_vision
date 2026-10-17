"""
Zone presence and dwell monitoring (pure Python, no camera/model/database dependencies).

A zone is a polygon in normalised image coordinates. For every tracked person the anchor point
(feet by default) is tested against each zone. To avoid alerts from a single noisy frame:

- presence must be confirmed for `min_frames` consecutive processed frames before a
  "zone_entered" event is emitted (restricted zones only),
- a "dwell_exceeded" event is emitted once per stay when continuous presence exceeds the
  zone's dwell threshold,
- a person leaving the zone for less than `exit_grace_seconds` (e.g. brief occlusion) does
  not restart the stay.

Track IDs are temporary tracker IDs. A track that is lost and re-acquired gets a new ID, so its
dwell time restarts: dwell figures are lower bounds, not identity-continuous measurements.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from vision.line_crossing import Box, Detection, anchor_of

Point = Tuple[float, float]


@dataclass(frozen=True)
class ZoneConfig:
    id: int
    name: str
    kind: str  # "restricted" | "monitored"
    polygon: Tuple[Point, ...]  # normalised 0..1
    dwell_seconds: Optional[float] = None


@dataclass(frozen=True)
class ZoneEvent:
    kind: str  # "zone_entered" | "dwell_exceeded"
    zone_id: int
    zone_name: str
    zone_kind: str
    track_id: int
    occurred_at: float
    dwell_seconds: float
    confidence: float
    box: Box


@dataclass
class _Stay:
    entered_at: float
    last_inside: float
    frames: int = 0
    announced: bool = False
    dwell_reported: bool = False
    confidences: List[float] = field(default_factory=list)


def point_in_polygon(x: float, y: float, polygon: Sequence[Point]) -> bool:
    """Ray casting; points on an edge may fall either way, which is fine for presence."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


class ZoneMonitor:
    def __init__(
        self,
        zones: Iterable[ZoneConfig] = (),
        min_confidence: float = 0.45,
        min_frames: int = 3,
        exit_grace_seconds: float = 2.0,
        anchor: str = "bottom",
    ):
        self.zones: List[ZoneConfig] = list(zones)
        self.min_confidence = min_confidence
        self.min_frames = min_frames
        self.exit_grace = exit_grace_seconds
        self.anchor = anchor
        self._stays: Dict[Tuple[int, int], _Stay] = {}

    def set_zones(self, zones: Iterable[ZoneConfig]) -> None:
        self.zones = list(zones)
        valid = {z.id for z in self.zones}
        self._stays = {k: v for k, v in self._stays.items() if k[0] in valid}

    def reset(self) -> None:
        self._stays.clear()

    def occupancy(self) -> Dict[int, int]:
        """People currently (confirmed) inside each zone."""
        counts: Dict[int, int] = {z.id: 0 for z in self.zones}
        for (zid, _tid), stay in self._stays.items():
            if stay.frames >= self.min_frames and zid in counts:
                counts[zid] += 1
        return counts

    def update(self, detections: Sequence[Detection], ts: float, frame_size: Tuple[int, int]) -> List[ZoneEvent]:
        if not self.zones:
            return []
        w, h = frame_size
        if w <= 0 or h <= 0:
            return []
        events: List[ZoneEvent] = []
        seen = set()
        for det in detections:
            if det.track_id is None or det.confidence < self.min_confidence:
                continue
            ax, ay = anchor_of(det.box, self.anchor)
            nx, ny = ax / w, ay / h
            for zone in self.zones:
                if not point_in_polygon(nx, ny, zone.polygon):
                    continue
                key = (zone.id, det.track_id)
                seen.add(key)
                stay = self._stays.get(key)
                if stay is None:
                    stay = self._stays[key] = _Stay(entered_at=ts, last_inside=ts)
                stay.last_inside = ts
                stay.frames += 1
                stay.confidences = (stay.confidences + [det.confidence])[-10:]
                conf = sum(stay.confidences) / len(stay.confidences)
                dwell = ts - stay.entered_at
                if stay.frames >= self.min_frames and not stay.announced:
                    stay.announced = True
                    if zone.kind == "restricted":
                        events.append(ZoneEvent("zone_entered", zone.id, zone.name, zone.kind, det.track_id, ts, dwell, conf, det.box))
                if (
                    zone.dwell_seconds
                    and not stay.dwell_reported
                    and stay.frames >= self.min_frames
                    and dwell >= zone.dwell_seconds
                ):
                    stay.dwell_reported = True
                    events.append(ZoneEvent("dwell_exceeded", zone.id, zone.name, zone.kind, det.track_id, ts, dwell, conf, det.box))
        for key in [k for k, s in self._stays.items() if k not in seen and ts - s.last_inside > self.exit_grace]:
            del self._stays[key]
        return events
