"""Event evidence storage. Only event-relevant crops are stored, never continuous video.

Files are kept per organization (org_<id>/<kind>/YYYY/MM/DD/<id>.jpg) so that storage limits and
deletion can be applied per tenant. They are served only through authenticated API routes.
"""

import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from config import settings

logger = logging.getLogger("viahind.snapshots")

USAGE_CACHE_SECONDS = 60.0
_usage_cache: Dict[int, Tuple[float, int]] = {}
_usage_lock = threading.Lock()


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


def organization_usage_bytes(organization_id: int, fresh: bool = False) -> int:
    """Bytes of evidence stored for one organization (cached briefly; walking the tree is not free)."""
    now = time.monotonic()
    with _usage_lock:
        cached = _usage_cache.get(organization_id)
        if cached and not fresh and now - cached[0] < USAGE_CACHE_SECONDS:
            return cached[1]
    total = 0
    base = snapshot_root() / f"org_{organization_id}"
    if base.is_dir():
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
    with _usage_lock:
        _usage_cache[organization_id] = (now, total)
    return total


def _add_usage(organization_id: int, delta: int) -> None:
    with _usage_lock:
        cached = _usage_cache.get(organization_id)
        if cached:
            _usage_cache[organization_id] = (cached[0], max(0, cached[1] + delta))


def save_snapshot(
    item_id: str,
    occurred_at: datetime,
    jpeg: Optional[bytes],
    organization_id: Optional[int] = None,
    limit_mb: int = 0,
    kind: str = "events",
) -> Tuple[Optional[str], str]:
    """Write a snapshot; returns (relative path, snapshot_status)."""
    if not jpeg:
        return None, "none"
    if storage_status()["low"]:
        logger.warning("Snapshot %s skipped: free disk space below MIN_FREE_DISK_MB", item_id)
        return None, "skipped_low_storage"
    if organization_id is not None and limit_mb > 0:
        if organization_usage_bytes(organization_id) + len(jpeg) > limit_mb * 1024 * 1024:
            logger.warning("Snapshot %s skipped: organization %s reached its evidence storage limit", item_id, organization_id)
            return None, "skipped_storage_limit"
    prefix = f"org_{organization_id}/{kind}/" if organization_id is not None else ""
    rel = f"{prefix}{occurred_at:%Y/%m/%d}/{item_id}.jpg"
    path = snapshot_root() / rel
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(jpeg)
        os.replace(tmp, path)
    except OSError:
        logger.exception("Failed to write snapshot %s", item_id)
        return None, "failed"
    if organization_id is not None:
        _add_usage(organization_id, len(jpeg))
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
            size = path.stat().st_size
            path.unlink()
            parts = Path(rel).parts
            if parts and parts[0].startswith("org_") and parts[0][4:].isdigit():
                _add_usage(int(parts[0][4:]), -size)
        except OSError:
            logger.warning("Could not delete snapshot %s", rel)
