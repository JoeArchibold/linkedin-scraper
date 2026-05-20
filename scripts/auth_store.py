"""OS keyring-backed storage for local auth state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE_NAME = "linkedin-games-data-collector"
LINKEDIN_STATE_KEY = "linkedin_state"
GOOGLE_TOKEN_KEY = "google_token"
CHUNK_SIZE = 900


class AuthStoreError(RuntimeError):
    """Raised when the OS credential store cannot be read or written."""


def _delete_secret(key: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except PasswordDeleteError:
        return
    except KeyringError as exc:
        raise AuthStoreError(f"Could not delete {key} from the OS credential store: {exc}") from exc


def _get_raw_secret(key: str) -> str | None:
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except KeyringError as exc:
        raise AuthStoreError(f"Could not read {key} from the OS credential store: {exc}") from exc


def _set_raw_secret(key: str, value: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, key, value)
    except KeyringError as exc:
        raise AuthStoreError(f"Could not save {key} to the OS credential store: {exc}") from exc


def _chunk_key(key: str, index: int) -> str:
    return f"{key}:chunk:{index}"


def _manifest_key(key: str) -> str:
    return f"{key}:chunks"


def _get_secret(key: str) -> str | None:
    manifest = _get_raw_secret(_manifest_key(key))
    if not manifest:
        return _get_raw_secret(key)

    try:
        count = int(manifest)
    except ValueError as exc:
        raise AuthStoreError(f"Invalid keyring chunk manifest for {key}") from exc

    chunks = []
    for index in range(count):
        chunk = _get_raw_secret(_chunk_key(key, index))
        if chunk is None:
            raise AuthStoreError(f"Missing keyring chunk {index} for {key}")
        chunks.append(chunk)
    return "".join(chunks)


def _set_secret(key: str, value: str) -> None:
    # Prefer chunked storage for all values so large browser state works with
    # Windows Credential Manager's per-secret size limits.
    chunks = [value[index:index + CHUNK_SIZE] for index in range(0, len(value), CHUNK_SIZE)]

    old_manifest = _get_raw_secret(_manifest_key(key))
    old_count = int(old_manifest) if old_manifest and old_manifest.isdigit() else 0

    for index, chunk in enumerate(chunks):
        _set_raw_secret(_chunk_key(key, index), chunk)
    _set_raw_secret(_manifest_key(key), str(len(chunks)))
    _delete_secret(key)

    for index in range(len(chunks), old_count):
        _delete_secret(_chunk_key(key, index))


def get_linkedin_state() -> dict[str, Any] | None:
    """Return saved Playwright storage state from the OS credential store."""
    value = _get_secret(LINKEDIN_STATE_KEY)
    if value is None:
        return None
    return json.loads(value)


def save_linkedin_state(state: dict[str, Any]) -> None:
    """Save Playwright storage state in the OS credential store."""
    _set_secret(LINKEDIN_STATE_KEY, json.dumps(state))


def get_google_token_json() -> str | None:
    """Return the cached Google OAuth user token JSON, if present."""
    return _get_secret(GOOGLE_TOKEN_KEY)


def save_google_token_json(token_json: str) -> None:
    """Save the Google OAuth user token JSON in the OS credential store."""
    _set_secret(GOOGLE_TOKEN_KEY, token_json)


def import_json_file_if_missing(key: str, path: Path) -> bool:
    """
    Import a legacy JSON auth file into the OS credential store if no secret
    exists yet. Returns True when an import was performed.
    """
    if _get_secret(key) is not None or not path.exists():
        return False

    data = json.loads(path.read_text(encoding="utf-8"))
    _set_secret(key, json.dumps(data))
    return True
