"""
Portable encrypted storage for local auth state.

Master-key resolution (first hit wins):
  1. $LINKEDIN_GAMES_MASTER_KEY env var (urlsafe base64 Fernet key)
  2. OS keyring (Credential Manager / Keychain / Secret Service)
  3. Passphrase prompt -> PBKDF2-HMAC-SHA256 (salt stored next to ciphertext)

Ciphertext lives in the user's per-OS data directory:
  Windows: %LOCALAPPDATA%\\linkedin-games\\
  macOS:   ~/Library/Application Support/linkedin-games/
  Linux:   $XDG_DATA_HOME/linkedin-games/  (~ ~/.local/share/...)

Files are written with mode 0600 on POSIX. A missing/rotated key produces a
clear "please re-run setup" error rather than a raw InvalidToken traceback.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from platformdirs import user_data_dir

APP_NAME = "linkedin-games"
SERVICE_NAME = "linkedin-games-data-collector"
MASTER_KEY_ENTRY = "fernet-master-key"
ENV_VAR = "LINKEDIN_GAMES_MASTER_KEY"
PBKDF2_ITERATIONS = 600_000

DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKEDIN_STATE_PATH = DATA_DIR / "linkedin_state.enc"
SALT_PATH = DATA_DIR / "passphrase.salt"


class AuthStoreError(RuntimeError):
    """Raised when the encrypted store cannot be read or written."""


# -- Master-key resolution ---------------------------------------------------

def _key_from_env() -> bytes | None:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return None
    try:
        Fernet(raw.encode())  # validate
    except Exception as exc:
        raise AuthStoreError(
            f"{ENV_VAR} is not a valid Fernet key: {exc}"
        ) from exc
    return raw.encode()


def _key_from_keyring(create_if_missing: bool) -> bytes | None:
    try:
        import keyring
        from keyring.errors import KeyringError, NoKeyringError
    except ImportError:
        return None

    try:
        existing = keyring.get_password(SERVICE_NAME, MASTER_KEY_ENTRY)
        if existing:
            return existing.encode()
        if not create_if_missing:
            return None
        new_key = Fernet.generate_key().decode()
        keyring.set_password(SERVICE_NAME, MASTER_KEY_ENTRY, new_key)
        return new_key.encode()
    except (NoKeyringError, KeyringError):
        # Headless Linux, broken DBus, locked keychain, etc. Fall through to
        # the passphrase fallback so the tool still works.
        return None


def _key_from_passphrase(create_if_missing: bool) -> bytes:
    if not sys.stdin.isatty():
        raise AuthStoreError(
            "No keyring backend is available and stdin is not interactive, "
            f"so no passphrase can be prompted. Set ${ENV_VAR} to a Fernet "
            "key (generate one with: python -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\")."
        )

    if SALT_PATH.exists():
        salt = SALT_PATH.read_bytes()
    elif create_if_missing:
        salt = os.urandom(16)
        SALT_PATH.write_bytes(salt)
        _chmod_user_only(SALT_PATH)
    else:
        raise AuthStoreError(
            "No saved passphrase salt found. Re-run setup_auth.py."
        )

    passphrase = getpass.getpass("Master passphrase: ").encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase))


def _resolve_master_key(create_if_missing: bool = False) -> bytes:
    key = _key_from_env()
    if key is not None:
        return key
    key = _key_from_keyring(create_if_missing)
    if key is not None:
        return key
    return _key_from_passphrase(create_if_missing)


# -- File I/O ----------------------------------------------------------------

def _chmod_user_only(path: Path) -> None:
    # On Windows, %LOCALAPPDATA% is already ACL-protected for the current user.
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _read_encrypted(path: Path) -> str | None:
    if not path.exists():
        return None
    key = _resolve_master_key(create_if_missing=False)
    try:
        return Fernet(key).decrypt(path.read_bytes()).decode()
    except InvalidToken as exc:
        raise AuthStoreError(
            f"Could not decrypt {path.name}. The master key may have changed "
            "or the file is corrupt. Delete it and re-run setup_auth.py."
        ) from exc


def _write_encrypted(path: Path, value: str) -> None:
    key = _resolve_master_key(create_if_missing=True)
    path.write_bytes(Fernet(key).encrypt(value.encode()))
    _chmod_user_only(path)


# -- Public API (signatures match the previous auth_store.py) ---------------

def get_linkedin_state() -> dict[str, Any] | None:
    """Return saved Playwright storage state, decrypting from disk."""
    raw = _read_encrypted(LINKEDIN_STATE_PATH)
    return json.loads(raw) if raw else None


def save_linkedin_state(state: dict[str, Any]) -> None:
    """Encrypt and save Playwright storage state."""
    _write_encrypted(LINKEDIN_STATE_PATH, json.dumps(state))


def delete_linkedin_state() -> bool:
    """
    Delete the encrypted LinkedIn session file.

    Returns True if a file was removed, False if there was nothing to delete.
    The Fernet master key in the OS credential store is left intact, so a later
    setup_auth.py run reuses it to encrypt the next session.
    """
    if LINKEDIN_STATE_PATH.exists():
        LINKEDIN_STATE_PATH.unlink()
        return True
    return False


def delete_master_key() -> dict[str, bool]:
    """
    Remove local Fernet key material: the OS keyring entry and the passphrase
    salt file (if present).

    Returns {"keyring": bool, "salt": bool} indicating what was actually removed.
    Does NOT (and cannot) unset $LINKEDIN_GAMES_MASTER_KEY in your environment —
    that takes precedence over the keyring, so unset it separately for a full
    rotation. After removing the key the encrypted session can no longer be
    decrypted, so callers should delete it too (see delete_linkedin_state); a
    later setup_auth.py run generates a fresh key.
    """
    removed = {"keyring": False, "salt": False}
    try:
        import keyring
        from keyring.errors import KeyringError, NoKeyringError
        try:
            if keyring.get_password(SERVICE_NAME, MASTER_KEY_ENTRY) is not None:
                keyring.delete_password(SERVICE_NAME, MASTER_KEY_ENTRY)
                removed["keyring"] = True
        except (NoKeyringError, KeyringError):
            pass
    except ImportError:
        pass
    if SALT_PATH.exists():
        SALT_PATH.unlink()
        removed["salt"] = True
    return removed
