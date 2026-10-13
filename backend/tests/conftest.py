"""
Test setup. Environment variables are set before any application module is imported so the
suite never touches backend/.env values, the real database, real cameras or model weights.
"""

import itertools
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP = Path(tempfile.mkdtemp(prefix="viahind-tests-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "DEBUG": "False",
        "SECRET_KEY": "test-secret-key-for-automated-tests-only-0123456789",
        "DATABASE_URL": f"sqlite:///{(TMP / 'boot.db').as_posix()}",
        "SNAPSHOT_DIR": str(TMP / "snapshots"),
        "TEST_VIDEO_DIR": str(TMP / "videos"),
        "STORAGE_DIR": str(TMP),
        "PERSON_MODEL_PATH": "",
        "ANOMALY_DETECTION_ENABLED": "False",
        "BOOTSTRAP_ADMIN_USERNAME": "",
        "BOOTSTRAP_ADMIN_PASSWORD": "",
        "MIN_FREE_DISK_MB": "1",
        "CORS_ORIGINS": "http://localhost:3000",
    }
)

import pytest  # noqa: E402

import db  # noqa: E402
from auth import hash_password, login_throttle  # noqa: E402
from models.entities import Camera, User  # noqa: E402

_counter = itertools.count()


@pytest.fixture(autouse=True)
def fresh_database():
    """Each test gets a new, fully migrated SQLite database."""
    from main import run_migrations

    path = TMP / f"test_{next(_counter)}.db"
    engine = db.make_engine(f"sqlite:///{path.as_posix()}")
    db.configure_engine(engine)
    run_migrations()
    login_throttle._failures.clear()
    yield engine
    engine.dispose()


@pytest.fixture
def snapshot_dir():
    from config import settings

    path = Path(settings.SNAPSHOT_DIR)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


ADMIN_PASSWORD = "AdminPass123"
OPERATOR_PASSWORD = "OperatorPass123"


@pytest.fixture
def users():
    with db.session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password(ADMIN_PASSWORD), role="admin"))
        s.add(User(username="operator", password_hash=hash_password(OPERATOR_PASSWORD), role="operator"))
    return {"admin": ADMIN_PASSWORD, "operator": OPERATOR_PASSWORD}


@pytest.fixture
def camera():
    with db.session_scope() as s:
        s.add(Camera(id="CAM-ENTRANCE-01", name="Main Entrance", location="Gate", source_type="browser"))
    return "CAM-ENTRANCE-01"


@pytest.fixture
def client(users):
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app, base_url="http://localhost") as c:
        yield c


def login(client, username: str, password: str):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


CSRF = {"X-VV-CSRF": "1"}
