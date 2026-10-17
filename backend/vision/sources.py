"""
Camera source handling: validation, encryption at rest, masking and resolution.

Source strings can contain camera credentials (rtsp://user:pass@host/...). They are:
- validated on input,
- encrypted in the database with a key derived from SECRET_KEY,
- never returned by the API (only a masked description is),
- optionally kept entirely out of the database with an "env:CAMERA_..." reference.

Network destinations are restricted (server-side request forgery protection): a camera URL must
resolve only to addresses inside CAMERA_ALLOWED_NETWORKS (private LAN ranges by default), and
loopback, link-local (including cloud metadata at 169.254.169.254), multicast, unspecified and
reserved addresses are always refused. The check runs when the source is saved and again every
time a worker opens it (a hostname could be re-pointed in between).
"""

import base64
import hashlib
import ipaddress
import os
import re
import socket
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union
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


DEFAULT_PORTS = {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443}


def _allowed_networks() -> List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]:
    nets = []
    for item in settings.CAMERA_ALLOWED_NETWORKS.split(","):
        item = item.strip()
        if item:
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                continue
    return nets


def address_allowed(address: str) -> Tuple[bool, str]:
    """Whether one resolved IP address is an acceptable camera destination."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False, "invalid address"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False, "loopback, link-local, multicast and reserved addresses are not allowed"
    if not any(ip in net for net in _allowed_networks()):
        return False, "the address is outside the camera networks allowed on this server (CAMERA_ALLOWED_NETWORKS)"
    return True, ""


def resolve_host(host: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise SourceError(f"The camera host name could not be resolved ({host}).") from exc
    return sorted({info[4][0] for info in infos})


def check_network_destination(url: str) -> Tuple[str, int, List[str]]:
    """Raise SourceError unless every address the URL's host resolves to is allowed."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise SourceError("The camera URL has no host.")
    try:
        port = parts.port or DEFAULT_PORTS.get(parts.scheme.lower(), 554)
    except ValueError as exc:
        raise SourceError("The camera URL has an invalid port.") from exc
    addresses = resolve_host(host, port)
    for address in addresses:
        ok, why = address_allowed(address)
        if not ok:
            raise SourceError(f"This camera address is not allowed: {why}.")
    return host, port, addresses


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
        check_network_destination(value)
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
        check_network_destination(value or "")
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


def probe_tcp(url: str, timeout: float) -> dict:
    """TCP reachability check with an operator-readable diagnosis. Never includes credentials."""
    host, port, addresses = check_network_destination(url)
    started = time.monotonic()
    last_error = None
    for address in addresses:
        try:
            with socket.create_connection((address, port), timeout=timeout):
                return {"ok": True, "port": port, "elapsed_ms": int((time.monotonic() - started) * 1000)}
        except socket.timeout:
            last_error = f"No response from {host}:{port} within {timeout:.0f}s. Check that the camera is powered on and on the same network as the server."
        except ConnectionRefusedError:
            last_error = f"{host} refused the connection on port {port}. The camera may use a different RTSP/HTTP port, or streaming is disabled in its settings."
        except OSError:
            last_error = f"{host}:{port} is unreachable from the server (no route). Check cabling, VLANs and firewall rules."
    return {"ok": False, "port": port, "message": last_error or "The camera could not be reached."}
