"""
Configuration for the LinkedIn Games score collector (CSV-only build).

`.env` lives next to this file. Copy `.env.example` to `.env` to customise.
Nothing in `.env` is required — the script runs with sensible defaults if
the file is absent.
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

# Path to the JSON layout file that controls which games appear in the output.
# See sheet_layout.py.
SHEET_LAYOUT_FILE = SCRIPTS_DIR / "sheet_layout.json"


# ── Output ─────────────────────────────────────────────────────────────────────

def _resolve_output_path() -> Path:
    """
    Where to write results.csv by default.

    Resolution order (first match wins):
      1. $RESULTS_CSV from .env or the environment — absolute or relative.
         Relative paths resolve against the current working directory.
      2. ./results.csv in the current working directory.

    The CLI `--output FILE` flag overrides this at runtime.
    """
    env_value = os.getenv("RESULTS_CSV")
    if env_value:
        path = Path(env_value).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return Path.cwd() / "results.csv"


DEFAULT_RESULTS_CSV = _resolve_output_path()


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
