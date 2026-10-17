"""Per-organization evidence policy (snapshot quality, size and storage limit), cached briefly
so camera workers never query the database per frame."""

import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple

from sqlalchemy.exc import SQLAlchemyError

from db import session_scope

CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class EvidencePolicy:
    jpeg_quality: int = 85
    max_width: int = 640
    storage_limit_mb: int = 2048


_cache: Dict[int, Tuple[float, EvidencePolicy]] = {}
_lock = threading.Lock()


def evidence_policy(organization_id: int) -> EvidencePolicy:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(organization_id)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    try:
        from services.site_settings import get_site_settings

        with session_scope() as db:
            row = get_site_settings(db, organization_id)
            policy = EvidencePolicy(row.snapshot_jpeg_quality, row.snapshot_max_width, row.snapshot_storage_limit_mb)
    except SQLAlchemyError:
        policy = cached[1] if cached else EvidencePolicy()
    with _lock:
        _cache[organization_id] = (now, policy)
    return policy


def invalidate(organization_id: int) -> None:
    with _lock:
        _cache.pop(organization_id, None)
