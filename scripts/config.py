"""
Configuration for the LinkedIn Games score collector (JSON store build).

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

def _resolve_env_path(var: str) -> Path | None:
    """
    Resolve an output-path environment variable (from .env or the environment).

    Returns the path if the variable is set, else None. Relative paths resolve
    against the current working directory.
    """
    env_value = os.getenv(var)
    if not env_value:
        return None
    path = Path(env_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


# JSON is the only direct-write store. A configured $RESULTS_JSON sets the
# default location; otherwise results.json in the current working directory is
# used. The `--output FILE` flag overrides this at runtime.
DEFAULT_RESULTS_JSON = _resolve_env_path("RESULTS_JSON")
DEFAULT_OUTPUT_PATH = DEFAULT_RESULTS_JSON or (Path.cwd() / "results.json")

# Optional CSV view of the JSON store. CSV is always derived from the JSON
# (see export_csv.py); it is never written directly. $RESULTS_CSV sets the
# destination for the opt-in `--export-csv` run (typically a path inside a
# Google Drive sync folder so the CSV reaches Sheets without OAuth). When unset,
# `--export-csv` falls back to the JSON path with a .csv suffix.
DEFAULT_RESULTS_CSV = _resolve_env_path("RESULTS_CSV")


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
