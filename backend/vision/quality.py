"""
Cheap image-quality probe used to detect a covered, obstructed, very dark or badly blurred camera.

Measures (on a downscaled grayscale frame):
- brightness: mean intensity (0-255). Near 0 = lens covered / no light.
- contrast:   standard deviation. Very low = uniform image (covered, pointed at a wall, fogged).
- sharpness:  variance of the Laplacian. Very low = out of focus / smeared lens.

The values are reported with the camera status; the alert engine decides when a sustained
degradation is worth an alert (see services/alert_rules.py, rule "camera_quality").
"""

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class QualitySample:
    brightness: float
    contrast: float
    sharpness: float
    measured_at: float

    def as_dict(self) -> dict:
        return {
            "brightness": round(self.brightness, 1),
            "contrast": round(self.contrast, 1),
            "sharpness": round(self.sharpness, 1),
            "measured_at": self.measured_at,
        }


def measure_quality(image: np.ndarray, ts: float, width: int = 160) -> Optional[QualitySample]:
    if image is None or image.size == 0 or image.ndim < 2:
        return None
    h, w = image.shape[:2]
    if w > width:
        image = cv2.resize(image, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    brightness = float(gray.mean())
    contrast = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return QualitySample(brightness, contrast, sharpness, ts)
