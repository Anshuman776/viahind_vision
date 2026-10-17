"""Symmetric encryption for integration secrets stored in the database (webhook secrets,
recipient lists). Keys are derived from SECRET_KEY with a per-purpose context."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from config import settings


class SecretError(ValueError):
    pass


def _fernet(purpose: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256((purpose + ":" + settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt_json(purpose: str, value: dict) -> str:
    return _fernet(purpose).encrypt(json.dumps(value, sort_keys=True).encode("utf-8")).decode("ascii")


def decrypt_json(purpose: str, token: str) -> dict:
    try:
        return json.loads(_fernet(purpose).decrypt(token.encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError) as exc:
        raise SecretError("Stored integration settings cannot be decrypted (was SECRET_KEY changed?). Re-enter them.") from exc
