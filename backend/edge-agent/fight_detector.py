"""
VIAHIND Vision Edge Agent - Video anomaly detector (VIAHIND-FightClassifier-MobileNetV3).

Modes
- "model":  a trained clip classifier (backend/vision/fight_model.py) loaded from FIGHT_MODEL_PATH,
            hash-verified, weights-only. Train one with: python manage.py train-fight-model --data <dir>
- "motion": no weights needed. Reports vigorous movement between people in close contact
            (backend/vision/motion_anomaly.py). It does not claim to recognise fights.

predict_clip(frame_sequence, people=None) returns
    {"is_anomaly": bool, "is_fight": bool, "label": str, "confidence_score": float,
     "threshold": float, "mode": str, "metrics": {...}, "requires_human_verification": True}
"""

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from vision import fight_model, motion_anomaly


class FightDetector:
    def __init__(
        self,
        model_version: str = "",
        threshold: Optional[float] = None,
        model_path: str = "",
        mode: str = "auto",
        device: str = "cpu",
        expected_sha256: str = "",
        motion_threshold: float = 2.5,
    ):
        self.device = device
        self.motion_threshold = motion_threshold
        self.model = None
        self.meta: Dict[str, Any] = {}
        mode = (mode or "auto").lower()
        if mode not in ("auto", "model", "motion"):
            raise ValueError("VIDEO_ANOMALY_MODE must be auto, model or motion.")
        if mode in ("auto", "model") and model_path:
            loaded = fight_model.load_checkpoint(Path(model_path), device, expected_sha256 or None)
            self.model, self.meta = loaded, loaded.meta
        elif mode == "model":
            raise FileNotFoundError("VIDEO_ANOMALY_MODE=model needs FIGHT_MODEL_PATH (train with manage.py train-fight-model).")
        self.mode = "model" if self.model is not None else "motion"
        self.model_version = self.meta.get("version") or model_version or ("motion-v1" if self.mode == "motion" else "unknown")
        self.threshold = float(threshold if threshold is not None else self.meta.get("threshold", 0.75))

    def predict_clip(self, frame_sequence: Sequence, people: Optional[Sequence] = None) -> Dict[str, Any]:
        if self.mode == "model":
            prob = fight_model.predict_probability(self.model, frame_sequence, self.device)
            hit = prob >= self.threshold
            return {
                "is_anomaly": hit, "is_fight": hit, "label": "Possible physical altercation",
                "confidence_score": round(prob, 4), "threshold": self.threshold, "mode": "model",
                "metrics": {"probability": round(prob, 4)}, "requires_human_verification": True,
            }
        if people is None:
            return {"is_anomaly": False, "is_fight": False, "label": motion_anomaly.LABEL, "confidence_score": 0.0,
                    "threshold": self.threshold, "mode": "motion", "metrics": {}, "requires_human_verification": True,
                    "note": "Motion mode needs person detection on the camera."}
        result = motion_anomaly.analyse_clip(frame_sequence, people, self.motion_threshold)
        return {
            "is_anomaly": result["is_anomaly"], "is_fight": False, "label": result["label"],
            "confidence_score": result["confidence_score"], "threshold": self.threshold, "mode": "motion",
            "metrics": result["metrics"], "requires_human_verification": True,
        }
