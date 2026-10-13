"""
Camera source handling: validation, encryption at rest, masking and resolution.

Source strings can contain camera credentials (rtsp://user:pass@host/...). They are:
- validated on input,
- encrypted in the database with a key derived from SECRET_KEY,
- never returned by the API (only a masked description is),
- optionally kept entirely out of the database with an "env:CAMERA_..." reference.
"""

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from config import settings

NETWORK_SCHEMES = ("rtsp", "rtsps", "http", "https")
ENV_REF = re.compile(r"^env:(CAMERA_[A-Z0-9_]{1,64})$")
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,120}\.(mp4|avi|mkv|mov|webm)$", re.IGNORECASE)


class SourceError(ValueError):
    """Invalid or unusable camera source. Messages are safe to show to operators."""


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("camera-source:" + settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt_source(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_source(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SourceError("The stored camera source cannot be decrypted (was SECRET_KEY changed?). Re-enter it in Settings.") from exc


def validate_source(source_type: str, value: Optional[str]) -> Optional[str]:
    """Normalise and validate a source for the given type. Returns the value to store."""
    value = (value or "").strip()
    if source_type == "browser":
        return None  # frames are pushed by an operator's browser; nothing to store
    if not value:
        raise SourceError("A camera source is required for this camera type.")
    if any(ord(c) < 32 for c in value) or len(value) > 2048:
        raise SourceError("The camera source contains invalid characters or is too long.")

    if source_type == "device":
        if not value.isdigit() or int(value) > 15:
            raise SourceError("A USB/device camera source must be a device index between 0 and 15.")
        return str(int(value))

    if source_type == "network":
        if ENV_REF.match(value):
            return value
        parts = urlsplit(value)
        if parts.scheme.lower() not in NETWORK_SCHEMES or not parts.hostname:
            raise SourceError("Network cameras need an rtsp://, rtsps://, http:// or https:// URL, or an env:CAMERA_... reference.")
        if " " in value:
            raise SourceError("The camera URL must not contain spaces.")
        return value

    if source_type == "file":
        if not settings.ALLOW_FILE_SOURCES:
            raise SourceError("Test video sources are disabled on this server (ALLOW_FILE_SOURCES=False).")
        if not FILE_NAME.match(value):
            raise SourceError("Enter only the file name of a clip placed in the server's test video folder.")
        return value

    raise SourceError("Unknown camera source type.")


def mask_source(source_type: str, value: Optional[str]) -> str:
    """A description of the source that is safe to show in the UI and logs."""
    if source_type == "browser":
        return "Browser camera (frames sent by a signed-in operator's device)"
    if not value:
        return "Not configured"
    if source_type == "device":
        return f"Server USB device {value}"
    if source_type == "file":
        return f"Test clip: {value}"
    if ENV_REF.match(value):
        return f"From server environment ({value[4:]})"
    parts = urlsplit(value)
    host = parts.hostname or "?"
    port = f":{parts.port}" if parts.port else ""
    auth = "***@" if parts.username or parts.password else ""
    path = parts.path if len(parts.path) <= 40 else parts.path[:37] + "..."
    return f"{parts.scheme}://{auth}{host}{port}{path}"


def resolve_source(source_type: str, value: Optional[str]) -> Union[int, str]:
    """Turn a stored source into something OpenCV can open."""
    if source_type == "device":
        return int(value or 0)
    if source_type == "network":
        match = ENV_REF.match(value or "")
        if match:
            resolved = os.getenv(match.group(1), "").strip()
            if not resolved:
                raise SourceError(f"Environment variable {match.group(1)} is not set on the server.")
            return resolved
        return value or ""
    if source_type == "file":
        if not settings.ALLOW_FILE_SOURCES:
            raise SourceError("Test video sources are disabled on this server.")
        base = Path(settings.TEST_VIDEO_DIR).resolve()
        path = (base / (value or "")).resolve()
        if base not in path.parents or not path.is_file():
            raise SourceError(f"Test clip not found in the test video folder ({base.name}/).")
        return str(path)
    raise SourceError("This camera type does not have a server-side source.")
