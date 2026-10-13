"""Event snapshot storage. Only event-relevant crops are stored, never continuous video."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from config import settings

logger = logging.getLogger("viahind.snapshots")


def snapshot_root() -> Path:
    root = Path(settings.SNAPSHOT_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def storage_status() -> dict:
    try:
        usage = shutil.disk_usage(snapshot_root())
    except OSError:
        return {"free_mb": None, "low": True, "min_free_mb": settings.MIN_FREE_DISK_MB}
    free_mb = usage.free // (1024 * 1024)
    return {"free_mb": int(free_mb), "low": free_mb < settings.MIN_FREE_DISK_MB, "min_free_mb": settings.MIN_FREE_DISK_MB}


def save_snapshot(event_id: str, occurred_at: datetime, jpeg: Optional[bytes]) -> Tuple[Optional[str], str]:
    """Write a snapshot; returns (relative path, snapshot_status)."""
    if not jpeg:
        return None, "none"
    if storage_status()["low"]:
        logger.warning("Snapshot for event %s skipped: free disk space below MIN_FREE_DISK_MB", event_id)
        return None, "skipped_low_storage"
    rel = f"{occurred_at:%Y/%m/%d}/{event_id}.jpg"
    path = snapshot_root() / rel
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(jpeg)
        os.replace(tmp, path)
    except OSError:
        logger.exception("Failed to write snapshot for event %s", event_id)
        return None, "failed"
    return rel, "saved"


def snapshot_file(rel: Optional[str]) -> Optional[Path]:
    """Resolve a stored relative path safely inside the snapshot directory."""
    if not rel:
        return None
    root = snapshot_root()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def delete_snapshot(rel: Optional[str]) -> None:
    path = snapshot_file(rel)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            logger.warning("Could not delete snapshot %s", rel)
