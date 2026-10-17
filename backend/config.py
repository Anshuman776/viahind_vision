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
    APP_NAME: str = os.getenv("APP_NAME", "VIAHIND Vision API")
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

    # Database
    # SQLite works out of the box. For PostgreSQL install `psycopg[binary]` and use
    # postgresql+psycopg://user:password@host:5432/viahind_vision
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./storage/viahind.db")
    DEMO_DATABASE_URL: str = os.getenv("DEMO_DATABASE_URL", "sqlite:///./storage/viahind_demo.db")

    # CORS
    @property
    def CORS_ORIGINS(self) -> List[str]:
        raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    # Video & Edge parameters
    # Resource limit: cameras processed at the same time by this server.
    MAX_SIMULTANEOUS_STREAMS: int = int(os.getenv("MAX_SIMULTANEOUS_STREAMS", "16"))
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

    # Camera network policy (server-side request forgery protection). Network camera URLs must
    # resolve to an address inside CAMERA_ALLOWED_NETWORKS. Loopback, link-local (including cloud
    # metadata 169.254.169.254), multicast and unspecified addresses are always refused.
    CAMERA_ALLOWED_NETWORKS: str = os.getenv("CAMERA_ALLOWED_NETWORKS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7")
    CAMERA_CONNECT_TEST_TIMEOUT: float = float(os.getenv("CAMERA_CONNECT_TEST_TIMEOUT", "8"))

    # Alerts and notifications
    ALERTS_ENABLED: bool = _bool("ALERTS_ENABLED", "True")
    ALERT_EVAL_INTERVAL_SECONDS: float = float(os.getenv("ALERT_EVAL_INTERVAL_SECONDS", "30"))
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "")
    SMTP_STARTTLS: bool = _bool("SMTP_STARTTLS", "True")
    # Webhooks normally go to the internet; private destinations need an explicit opt-in.
    WEBHOOK_ALLOW_PRIVATE: bool = _bool("WEBHOOK_ALLOW_PRIVATE", "False")
    # Optional: create notification channels for the default organization at startup.
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "")
    # Attach evidence snapshots to channels created from .env (email/Telegram leave your premises).
    ALERT_ATTACH_SNAPSHOT: bool = _bool("ALERT_ATTACH_SNAPSHOT", "True")
    ALERT_MIN_SEVERITY: str = os.getenv("ALERT_MIN_SEVERITY", "medium")
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")

    # Event-level ML anomaly detection (Isolation Forest baseline, services/ml_anomaly.py)
    MODEL_DIR: Path = _path("MODEL_DIR", "./storage/models")
    ML_ANOMALY_ENABLED: bool = _bool("ML_ANOMALY_ENABLED", "True")
    ML_MIN_TRAINING_HOURS: int = int(os.getenv("ML_MIN_TRAINING_HOURS", "168"))
    ML_MIN_TRAINING_DAYS: int = int(os.getenv("ML_MIN_TRAINING_DAYS", "7"))

    # Hybrid deployment. standalone: no sync. edge: push events to SYNC_URL. cloud: accept pushes.
    DEPLOYMENT_MODE: str = os.getenv("DEPLOYMENT_MODE", "standalone")
    SYNC_URL: str = os.getenv("SYNC_URL", "")
    SYNC_NODE_ID: str = os.getenv("SYNC_NODE_ID", "")
    SYNC_TOKEN: str = os.getenv("SYNC_TOKEN", "")
    SYNC_INTERVAL_SECONDS: float = float(os.getenv("SYNC_INTERVAL_SECONDS", "15"))
    SYNC_BATCH_SIZE: int = int(os.getenv("SYNC_BATCH_SIZE", "200"))

    # API rate limiting (per client address, in-process)
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "600"))

    # Video anomaly detector (edge-agent/fight_detector.py via vision/anomaly.py).
    # auto: trained classifier when FIGHT_MODEL_PATH is set, else the weight-free motion detector.
    ANOMALY_DETECTION_ENABLED: bool = _bool("ANOMALY_DETECTION_ENABLED", "True")
    VIDEO_ANOMALY_MODE: str = os.getenv("VIDEO_ANOMALY_MODE", "auto")
    FIGHT_DETECTOR_MODEL: str = os.getenv("FIGHT_DETECTOR_MODEL", "VIAHIND-FightClassifier-MobileNetV3")
    FIGHT_DETECTOR_VERSION: str = os.getenv("FIGHT_DETECTOR_VERSION", "")
    # Trained weights (.pt with its .json metadata next to it), e.g. ./storage/models/video/fight_classifier_<v>.pt
    FIGHT_MODEL_PATH: str = os.getenv("FIGHT_MODEL_PATH", "")
    FIGHT_MODEL_SHA256: str = os.getenv("FIGHT_MODEL_SHA256", "")
    # Decision threshold for the classifier; when unset, the threshold chosen at training time is used.
    FIGHT_CONFIDENCE_THRESHOLD: float = float(os.getenv("FIGHT_CONFIDENCE_THRESHOLD", "0.75"))
    FIGHT_CONFIDENCE_THRESHOLD_SET: bool = bool(os.getenv("FIGHT_CONFIDENCE_THRESHOLD", "").strip())
    # Motion mode: mean optical-flow magnitude (pixels per sampled frame at 112 px) counted as vigorous.
    MOTION_ANOMALY_THRESHOLD: float = float(os.getenv("MOTION_ANOMALY_THRESHOLD", "2.5"))
    ANOMALY_SAMPLE_EVERY_N_FRAMES: int = int(os.getenv("ANOMALY_SAMPLE_EVERY_N_FRAMES", "1"))
    ANOMALY_CLIP_LENGTH: int = int(os.getenv("ANOMALY_CLIP_LENGTH", "16"))
    # Positive clips in a row required before an alert (reduces one-off false alarms).
    ANOMALY_MIN_CONSECUTIVE_CLIPS: int = int(os.getenv("ANOMALY_MIN_CONSECUTIVE_CLIPS", "2"))

    # Initial values for a new organization's settings record
    ACTIVE_FACILITY_NAME: str = os.getenv("ACTIVE_FACILITY_NAME", "My Business")
    SITE_TIMEZONE: str = os.getenv("SITE_TIMEZONE", "Asia/Kolkata")

    @property
    def IS_EDGE(self) -> bool:
        return self.DEPLOYMENT_MODE.lower() == "edge"

    @property
    def IS_CLOUD(self) -> bool:
        return self.DEPLOYMENT_MODE.lower() == "cloud"

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
            if self.DEBUG:
                raise RuntimeError("DEBUG must be False in production.")
        if self.DEPLOYMENT_MODE.lower() not in ("standalone", "edge", "cloud"):
            raise RuntimeError("DEPLOYMENT_MODE must be standalone, edge or cloud.")
        if self.IS_EDGE and not (self.SYNC_URL and self.SYNC_NODE_ID and self.SYNC_TOKEN):
            raise RuntimeError("DEPLOYMENT_MODE=edge needs SYNC_URL, SYNC_NODE_ID and SYNC_TOKEN.")
        if self.IS_EDGE and self.IS_PRODUCTION and not self.SYNC_URL.startswith("https://"):
            raise RuntimeError("SYNC_URL must use https:// in production.")


settings = Settings()
