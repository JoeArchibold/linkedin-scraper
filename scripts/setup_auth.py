"""
One-time setup script. Run this before using collector.py.

Opens a visible Chromium browser so you can log in to LinkedIn, then saves
the session state (cookies + localStorage) to an encrypted file in your per-OS
data directory.

After this runs successfully, collector.py can collect scores fully headless.

Usage:
    python setup_auth.py              # log in and save the encrypted session
    python setup_auth.py --delete     # delete the saved session (keeps the key)
    python setup_auth.py --delete-key # full local wipe: session + Fernet key
"""

import argparse
import logging
import os
import sys

from playwright.sync_api import sync_playwright

from auth_store import (
    ENV_VAR,
    LINKEDIN_STATE_PATH,
    SALT_PATH,
    delete_linkedin_state,
    delete_master_key,
    save_linkedin_state,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def setup_linkedin() -> None:
    """Open a browser, wait for manual LinkedIn login, save the session."""
    logger.info("=" * 60)
    logger.info("LinkedIn authentication")
    logger.info("=" * 60)
    logger.info("A browser window will open. Log in to LinkedIn normally.")
    logger.info("Once your feed/home page has loaded, come back here and")
    logger.info("press ENTER to save your session.")
    logger.info("")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        input("\n>>> Press ENTER after you have logged in to LinkedIn ... ")

        save_linkedin_state(context.storage_state())
        logger.info("LinkedIn session saved to the encrypted store.")
        browser.close()


def _warn_if_env_key_set() -> None:
    if os.environ.get(ENV_VAR):
        logger.warning(
            f"{ENV_VAR} is set in your environment and takes precedence over the "
            "keyring, so the key it holds is still in effect. Unset it separately "
            "to fully rotate the key."
        )


def _note_no_server_revocation() -> None:
    logger.info(
        "Note: this does not revoke the session on LinkedIn. If the token may "
        "have leaked, also sign out the device or change your password on LinkedIn."
    )


def delete_session() -> None:
    """Delete the saved encrypted session (keeps the Fernet key in the keyring)."""
    if delete_linkedin_state():
        logger.info(f"Deleted saved LinkedIn session: {LINKEDIN_STATE_PATH}")
    else:
        logger.info(f"No saved LinkedIn session found at {LINKEDIN_STATE_PATH}; nothing to delete.")
    logger.info(
        "The Fernet key in the OS credential store was kept; re-run "
        "setup_auth.py to log in again."
    )
    _note_no_server_revocation()


def delete_key() -> None:
    """Full local wipe: delete the session, the keyring key, and the salt."""
    session_removed = delete_linkedin_state()
    removed = delete_master_key()

    if session_removed:
        logger.info(f"Deleted saved LinkedIn session: {LINKEDIN_STATE_PATH}")
    else:
        logger.info(f"No saved LinkedIn session found at {LINKEDIN_STATE_PATH}.")
    logger.info(
        "Removed Fernet key from the OS credential store."
        if removed["keyring"]
        else "No Fernet key found in the OS credential store."
    )
    if removed["salt"]:
        logger.info(f"Removed passphrase salt: {SALT_PATH}")

    _warn_if_env_key_set()
    logger.info(
        "Full local wipe complete. Re-run setup_auth.py to generate a new key "
        "and log in again."
    )
    _note_no_server_revocation()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up (or delete) the saved LinkedIn session for the collector."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--delete",
        action="store_true",
        help="Delete the saved encrypted LinkedIn session and exit (does not log "
             "in). The Fernet key in the OS credential store is kept.",
    )
    group.add_argument(
        "--delete-key",
        action="store_true",
        help="Full local wipe: delete the saved session AND remove the Fernet key "
             "(keyring entry + passphrase salt). Re-run setup_auth.py afterward to "
             "generate a new key and log in.",
    )
    args = parser.parse_args()

    if args.delete_key:
        delete_key()
        return 0
    if args.delete:
        delete_session()
        return 0

    setup_linkedin()
    logger.info("")
    logger.info("Setup complete. You can now run collector.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
