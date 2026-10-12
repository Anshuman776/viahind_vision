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

class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "VIAHIND Vision Security Analytics API")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    API_V1_PREFIX: str = os.getenv("API_V1_PREFIX", "/api/v1")

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "viahind-default-secret-change-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

    # Database & Redis
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://viahind:password@localhost:5432/viahind_vision")
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

    # AI Classifier parameters
    FIGHT_DETECTOR_MODEL: str = os.getenv("FIGHT_DETECTOR_MODEL", "VIAHIND-FightClassifier-MobileNetV3")
    FIGHT_DETECTOR_VERSION: str = os.getenv("FIGHT_DETECTOR_VERSION", "v2.4.1-edge")
    FIGHT_CONFIDENCE_THRESHOLD: float = float(os.getenv("FIGHT_CONFIDENCE_THRESHOLD", "0.75"))
    ENABLE_SYNTHETIC_MOCK_FALLBACK: bool = os.getenv("ENABLE_SYNTHETIC_MOCK_FALLBACK", "True").lower() in ("true", "1")

    # Facility info
    ACTIVE_FACILITY_ID: str = os.getenv("ACTIVE_FACILITY_ID", "FAC-PG-BLOCK-A")
    ACTIVE_FACILITY_NAME: str = os.getenv("ACTIVE_FACILITY_NAME", "PG Block A - Multi-Floor Residence")
    FLOORS_COUNT: int = int(os.getenv("FLOORS_COUNT", "5"))

settings = Settings()
