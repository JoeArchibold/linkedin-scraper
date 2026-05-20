"""
One-time setup script. Run this before using main.py.

It does two things:
  1. Opens a visible Chromium browser so you can log in to LinkedIn,
     then saves the session state (cookies) to the OS credential store.
  2. Triggers the Google OAuth2 consent flow and saves a token to
     the OS credential store.

After this runs successfully, main.py can run fully headless.
"""

import sys
import logging
from playwright.sync_api import sync_playwright

from config import GOOGLE_CREDENTIALS_FILE
from auth_store import save_linkedin_state
from sheets_updater import _get_credentials

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def setup_linkedin() -> None:
    """Open a browser, wait for manual LinkedIn login, save the session."""
    logger.info("=" * 60)
    logger.info("STEP 1: LinkedIn authentication")
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
        logger.info("LinkedIn session saved to the OS credential store.")
        browser.close()


def setup_google() -> None:
    """Trigger the Google OAuth2 flow and cache the resulting token."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: Google Sheets authentication")
    logger.info("=" * 60)

    if not GOOGLE_CREDENTIALS_FILE.exists():
        logger.error(
            f"Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}\n\n"
            "To create it:\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. Create a project (or select an existing one)\n"
            "  3. Enable the Google Sheets API\n"
            "  4. Create an OAuth 2.0 Client ID (Desktop app)\n"
            "  5. Download the JSON and save it as:\n"
            f"     {GOOGLE_CREDENTIALS_FILE}\n"
        )
        sys.exit(1)

    logger.info("A browser window will open for Google consent.")
    logger.info("Sign in with the account that owns the spreadsheet.")
    _get_credentials()
    logger.info("Google token saved to the OS credential store.")


if __name__ == "__main__":
    setup_linkedin()
    setup_google()
    logger.info("")
    logger.info("✓ Setup complete! You can now run main.py daily.")
