"""
One-time setup script. Run this before using main.py.

Opens a visible Chromium browser so you can log in to LinkedIn, then saves
the session state (cookies + localStorage) to an encrypted file in your per-OS
data directory.

After this runs successfully, main.py can collect scores fully headless.
"""

import logging
from playwright.sync_api import sync_playwright

from auth_store import save_linkedin_state

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


if __name__ == "__main__":
    setup_linkedin()
    logger.info("")
    logger.info("Setup complete. You can now run main.py.")
