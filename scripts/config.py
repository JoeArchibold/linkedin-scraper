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

# Legacy Playwright browser state file. Existing files are imported into keyring.
LINKEDIN_STATE_FILE = AUTH_DIR / "linkedin_state.json"

# Google OAuth2 credentials downloaded from Google Cloud Console
GOOGLE_CREDENTIALS_FILE = AUTH_DIR / "google_credentials.json"

# Legacy Google OAuth2 token file. Existing files are imported into keyring.
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
GAMES = [
    {
        "name":    "Zip",
        "url":     "https://www.linkedin.com/games/zip/results/",
        "is_time": True,   # True = MM:SS score, False = integer guesses (Pinpoint)
    },
    {
        "name":    "Tango",
        "url":     "https://www.linkedin.com/games/tango/results/",
        "is_time": True,
    },
    {
        "name":    "Queens",
        "url":     "https://www.linkedin.com/games/queens/results/",
        "is_time": True,
    },
    {
        "name":    "Patches",
        "url":     "https://www.linkedin.com/games/patches/results/",
        "is_time": True,
    },
    {
        "name":    "Mini Sudoku",
        "url":     "https://www.linkedin.com/games/mini-sudoku/results/",
        "is_time": True,
    },
    {
        "name":    "CrossClimb",
        "url":     "https://www.linkedin.com/games/crossclimb/results/",
        "is_time": True,
    },
    {
        "name":    "Pinpoint",
        "url":     "https://www.linkedin.com/games/pinpoint/results/",
        "is_time": False,  # Returns guesses (integer), not a time
    },
]

# Google Sheets column layout (score col, avg col) for each game in order
# Columns: A=date, B=Zip, C=ZipAvg, D=Tango, E=TangoAvg, ... N=Pinpoint, O=PinpointAvg, P=DayOfWeek
SHEET_COLUMNS = [
    ("B", "C"),   # Zip
    ("D", "E"),   # Tango
    ("F", "G"),   # Queens
    ("H", "I"),   # Patches
    ("J", "K"),   # Mini Sudoku
    ("L", "M"),   # CrossClimb
    ("N", "O"),   # Pinpoint
]
