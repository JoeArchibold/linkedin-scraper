"""
Configuration for LinkedIn Games score tracker.
Sensitive values (spreadsheet ID, worksheet name) are loaded from a .env
file in the same directory as this script. Copy .env.example to .env and
fill in your values before running for the first time.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).parent
AUTH_DIR = SCRIPTS_DIR / "auth"
AUTH_DIR.mkdir(exist_ok=True)

# Legacy Playwright browser state file. If present, it is migrated into the
# encrypted store on first run and can then be deleted.
LINKEDIN_STATE_FILE = AUTH_DIR / "linkedin_state.json"

# Google OAuth2 credentials downloaded from Google Cloud Console
GOOGLE_CREDENTIALS_FILE = AUTH_DIR / "google_credentials.json"

# Legacy Google OAuth2 token file. If present, it is migrated into the
# encrypted store on first run and can then be deleted.
GOOGLE_TOKEN_FILE = AUTH_DIR / "google_token.json"

# ── Google Sheets ──────────────────────────────────────────────────────────────
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1")

if not SPREADSHEET_ID:
    raise EnvironmentError(
        "SPREADSHEET_ID is not set. "
        "Copy .env.example to .env and add your spreadsheet ID."
    )

# ── LinkedIn Games ─────────────────────────────────────────────────────────────
# `key` is the stable identifier used by sheet_layout.json. `name` is the
# human-readable display name used for log lines, scraper lookups, and as the
# base for column headers.
GAMES = [
    {
        "key":     "zip",
        "name":    "Zip",
        "url":     "https://www.linkedin.com/games/zip/results/",
        "is_time": True,   # True = MM:SS score, False = integer guesses (Pinpoint)
    },
    {
        "key":     "tango",
        "name":    "Tango",
        "url":     "https://www.linkedin.com/games/tango/results/",
        "is_time": True,
    },
    {
        "key":     "queens",
        "name":    "Queens",
        "url":     "https://www.linkedin.com/games/queens/results/",
        "is_time": True,
    },
    {
        "key":     "patches",
        "name":    "Patches",
        "url":     "https://www.linkedin.com/games/patches/results/",
        "is_time": True,
    },
    {
        "key":     "mini_sudoku",
        "name":    "Mini Sudoku",
        "url":     "https://www.linkedin.com/games/mini-sudoku/results/",
        "is_time": True,
    },
    {
        "key":     "crossclimb",
        "name":    "CrossClimb",
        "url":     "https://www.linkedin.com/games/crossclimb/results/",
        "is_time": True,
    },
    {
        "key":     "wend",
        "name":    "Wend",
        "url":     "https://www.linkedin.com/games/wend/results/",
        "is_time": True,
    },
    {
        "key":     "pinpoint",
        "name":    "Pinpoint",
        "url":     "https://www.linkedin.com/games/pinpoint/results/",
        "is_time": False,  # Returns guesses (integer), not a time
    },
]

# Path to the JSON layout file that controls which games appear in the output,
# in what order, and whether puzzle numbers are written. See sheet_layout.py.
SHEET_LAYOUT_FILE = SCRIPTS_DIR / "sheet_layout.json"
