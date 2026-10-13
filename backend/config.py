"""
VIAHIND Vision - Backend Configuration & Environment Loader
Loads settings from .env with fallback defaults for local and production deployments.
"""

import os
from pathlib import Path
from typing import List

# Determine base directory and .env path
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# Load environment variables from .env if python-dotenv is present
try:
    from dotenv import load_dotenv
    if ENV_FILE.exists():
        load_dotenv(dotenv_path=ENV_FILE)
except ImportError:
    pass


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "t", "yes")


def _path(name: str, default: str) -> Path:
    """Resolve a path setting relative to the backend directory."""
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else (BASE_DIR / value).resolve()


DEFAULT_SECRET = "viahind-default-secret-change-in-production"


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "VIAHIND Vision Security Analytics API")
    # development | demo | production. "demo" serves synthetic records from a separate database.
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = _bool("DEBUG", "True")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    API_V1_PREFIX: str = os.getenv("API_V1_PREFIX", "/api/v1")

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", DEFAULT_SECRET)
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "vv_session")
    COOKIE_SECURE: bool = _bool("COOKIE_SECURE", "False")
    BOOTSTRAP_ADMIN_USERNAME: str = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_PASSWORD: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    # Database & Redis
    # SQLite works out of the box. For PostgreSQL install `psycopg[binary]` and use
    # postgresql+psycopg://user:password@host:5432/viahind_vision
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./storage/viahind.db")
    DEMO_DATABASE_URL: str = os.getenv("DEMO_DATABASE_URL", "sqlite:///./storage/viahind_demo.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # CORS
    @property
    def CORS_ORIGINS(self) -> List[str]:
        raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    # Video & Edge parameters
    RTSP_BROKER_URL: str = os.getenv("RTSP_BROKER_URL", "rtsp://localhost:8554/live")
    MAX_SIMULTANEOUS_STREAMS: int = int(os.getenv("MAX_SIMULTANEOUS_STREAMS", "16"))
    EVIDENCE_STORAGE_DIR: str = os.getenv("EVIDENCE_STORAGE_DIR", "./storage/evidence")
    STORAGE_DIR: Path = _path("STORAGE_DIR", "./storage")
    SNAPSHOT_DIR: Path = _path("SNAPSHOT_DIR", "./storage/snapshots")
    # Pre-recorded clips that may be used as a "file" camera source (development/testing).
    TEST_VIDEO_DIR: Path = _path("TEST_VIDEO_DIR", "./storage/test_videos")
    ALLOW_FILE_SOURCES: bool = _bool("ALLOW_FILE_SOURCES", "True")
    MIN_FREE_DISK_MB: int = int(os.getenv("MIN_FREE_DISK_MB", "500"))
    MAX_INGEST_FRAME_BYTES: int = int(os.getenv("MAX_INGEST_FRAME_BYTES", str(2 * 1024 * 1024)))

    # Person detection (YOLO + ByteTrack). Leave PERSON_MODEL_PATH empty to run cameras
    # without detection; weights are never downloaded automatically.
    PERSON_MODEL_PATH: str = os.getenv("PERSON_MODEL_PATH", "")
    PERSON_TRACKER_CONFIG: str = os.getenv("PERSON_TRACKER_CONFIG", "bytetrack.yaml")
    DETECTION_MAX_FPS: float = float(os.getenv("DETECTION_MAX_FPS", "8"))
    DETECTION_DEVICE: str = os.getenv("DETECTION_DEVICE", "cpu")
    VIEWER_MAX_FPS: float = float(os.getenv("VIEWER_MAX_FPS", "8"))
    # Seconds without a frame before a live camera is reported as disconnected.
    CAMERA_STALE_SECONDS: float = float(os.getenv("CAMERA_STALE_SECONDS", "5"))

    # AI Classifier parameters (existing edge-agent fight classifier, see vision/anomaly.py)
    FIGHT_DETECTOR_MODEL: str = os.getenv("FIGHT_DETECTOR_MODEL", "VIAHIND-FightClassifier-MobileNetV3")
    FIGHT_DETECTOR_VERSION: str = os.getenv("FIGHT_DETECTOR_VERSION", "v2.4.1-edge")
    FIGHT_CONFIDENCE_THRESHOLD: float = float(os.getenv("FIGHT_CONFIDENCE_THRESHOLD", "0.75"))
    ENABLE_SYNTHETIC_MOCK_FALLBACK: bool = os.getenv("ENABLE_SYNTHETIC_MOCK_FALLBACK", "True").lower() in ("true", "1")
    ANOMALY_DETECTION_ENABLED: bool = _bool("ANOMALY_DETECTION_ENABLED", "False")
    ANOMALY_SAMPLE_EVERY_N_FRAMES: int = int(os.getenv("ANOMALY_SAMPLE_EVERY_N_FRAMES", "3"))
    ANOMALY_CLIP_LENGTH: int = int(os.getenv("ANOMALY_CLIP_LENGTH", "16"))

    # Facility info (initial values for the site settings record)
    ACTIVE_FACILITY_ID: str = os.getenv("ACTIVE_FACILITY_ID", "FAC-PG-BLOCK-A")
    ACTIVE_FACILITY_NAME: str = os.getenv("ACTIVE_FACILITY_NAME", "PG Block A - Multi-Floor Residence")
    SITE_TIMEZONE: str = os.getenv("SITE_TIMEZONE", "Asia/Kolkata")
    FLOORS_COUNT: int = int(os.getenv("FLOORS_COUNT", "5"))

    @property
    def IS_DEMO(self) -> bool:
        return self.APP_ENV.lower() == "demo"

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def EFFECTIVE_DATABASE_URL(self) -> str:
        return self.DEMO_DATABASE_URL if self.IS_DEMO else self.DATABASE_URL

    def validate_for_startup(self) -> None:
        """Refuse to start a production deployment with unsafe defaults."""
        if self.IS_PRODUCTION:
            if self.SECRET_KEY == DEFAULT_SECRET or len(self.SECRET_KEY) < 32 or "change" in self.SECRET_KEY:
                raise RuntimeError("SECRET_KEY must be a strong random value (32+ chars) in production.")
            if not self.COOKIE_SECURE:
                raise RuntimeError("COOKIE_SECURE must be True in production (serve over HTTPS).")


settings = Settings()
