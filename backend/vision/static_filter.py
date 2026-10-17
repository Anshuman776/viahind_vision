"""
Static-object filter for the person detector.

Small YOLO models sometimes label things that look like people as "person": clothes on a hanger or
a chair, a bag, a poster, a mannequin. Such objects have one thing in common: they sit perfectly
still from the moment they are first seen. People walk into view.

A track that has not moved since it first appeared, for `hold_seconds`, is treated as an object
and dropped from counting, zones, the fight model and the live overlay. Once a track has moved it
is a person for the rest of its life, so a resident who walks in and then sits still is still
counted. The only case this hides is a person who was already sitting perfectly still when the
camera started; they reappear as soon as they move.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from vision.line_crossing import Detection


@dataclass
class _Track:
    first_seen: float
    last_seen: float
    cx: float
    cy: float
    w: float
    h: float
    moved: bool = False


class StaticObjectFilter:
    def __init__(self, hold_seconds: float = 10.0, move_fraction: float = 0.02, size_change: float = 0.25,
                 forget_seconds: float = 5.0):
        self.hold_seconds = hold_seconds
        self.move_fraction = move_fraction  # of the frame diagonal
        self.size_change = size_change      # relative change of box width or height
        self.forget_seconds = forget_seconds
        self._tracks: Dict[int, _Track] = {}
        self.suppressed = 0                 # objects hidden in the last update

    @property
    def enabled(self) -> bool:
        return self.hold_seconds > 0

    def reset(self) -> None:
        self._tracks.clear()

    def is_static(self, track_id: int, now: float) -> bool:
        t = self._tracks.get(track_id)
        return t is not None and not t.moved and now - t.first_seen >= self.hold_seconds

    def update(self, detections: Sequence[Detection], now: float, frame_size: Tuple[int, int]) -> List[Detection]:
        """Return the detections that are (or may still be) people."""
        if not self.enabled:
            return list(detections)
        diag = math.hypot(*frame_size) or 1.0
        kept: List[Detection] = []
        self.suppressed = 0
        for det in detections:
            if det.track_id is None:
                kept.append(det)
                continue
            x1, y1, x2, y2 = det.box
            cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, max(1.0, x2 - x1), max(1.0, y2 - y1)
            t = self._tracks.get(det.track_id)
            if t is None:
                t = self._tracks[det.track_id] = _Track(now, now, cx, cy, w, h)
            else:
                t.last_seen = now
                if not t.moved and (
                    math.hypot(cx - t.cx, cy - t.cy) > self.move_fraction * diag
                    or abs(w - t.w) > self.size_change * t.w
                    or abs(h - t.h) > self.size_change * t.h
                ):
                    t.moved = True
            if self.is_static(det.track_id, now):
                self.suppressed += 1
                continue
            kept.append(det)
        for tid in [tid for tid, t in self._tracks.items() if now - t.last_seen > self.forget_seconds]:
            del self._tracks[tid]
        return kept
