"""
Google Sheets updater for LinkedIn Games scores.

Uses OAuth2 (gspread + google-auth-oauthlib). On first run it opens a
browser for the one-time consent flow and caches a token in the OS credential
store.
Subsequent runs are fully headless.

Spreadsheet layout:
  A  = Date
  B  = Zip time         C  = Zip avg
  D  = Tango time       E  = Tango avg
  F  = Queens time      G  = Queens avg
  H  = Patches time     I  = Patches avg
  J  = Mini Sudoku time K  = Mini Sudoku avg
  L  = CrossClimb time  M  = CrossClimb avg
  N  = Pinpoint guesses O  = Pinpoint avg
  P  = Day of week
"""

import logging
import json
from datetime import date, datetime
from typing import Optional

import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from config import (
    SPREADSHEET_ID,
    WORKSHEET_NAME,
    GAMES,
    SHEET_COLUMNS,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
)
from auth_store import (
    GOOGLE_TOKEN_KEY,
    get_google_token_json,
    import_json_file_if_missing,
    save_google_token_json,
)
from linkedin_scraper import GameResult

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column letter → 0-based index (A=0, B=1, …)
def _col_idx(letter: str) -> int:
    return ord(letter.upper()) - ord("A")


def _get_credentials() -> Credentials:
    """Return valid OAuth2 credentials, refreshing or re-authorising as needed."""
    creds: Optional[Credentials] = None

    imported = import_json_file_if_missing(GOOGLE_TOKEN_KEY, GOOGLE_TOKEN_FILE)
    if imported:
        logger.info("Imported legacy Google token file into the OS credential store.")

    token_json = get_google_token_json()
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing Google token …")
            creds.refresh(Request())
        else:
            if not GOOGLE_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}\n"
                    "Download it from Google Cloud Console → APIs & Services → "
                    "Credentials and save as auth/google_credentials.json"
                )
            logger.info("Opening browser for Google OAuth consent …")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Cache for next run
        save_google_token_json(creds.to_json())
        logger.info("Google token saved to the OS credential store.")

    return creds


def get_today_state(today: date) -> tuple[Optional[int], list[str]]:
    """
    Check the spreadsheet for today's row.

    Returns (row_num, missing_game_names):
      - row_num is None if no row exists for today.
      - missing_game_names is a list of game names whose score cell is blank.
        An empty list means all scores are already present.
    """
    today_str = f"{today.month}/{today.day}/{today.year}"
    ws = _open_worksheet()
    row_num = _find_today_row(ws, today_str, today)

    if row_num is None:
        return None, []

    row_values = ws.row_values(row_num)
    missing = []
    for game, (score_col, _) in zip(GAMES, SHEET_COLUMNS):
        idx = _col_idx(score_col)
        if idx >= len(row_values) or not row_values[idx].strip():
            missing.append(game["name"])

    return row_num, missing


def _open_worksheet() -> gspread.Worksheet:
    creds = _get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(WORKSHEET_NAME)


def _find_today_row(ws: gspread.Worksheet, today_str: str, today: date) -> Optional[int]:
    """
    Return the 1-based row index if today's date already exists in column A,
    else None. Checks both 'M/D/YYYY' and 'MM/DD/YYYY' formats.
    """
    col_a = ws.col_values(1)  # 1-based column index
    for i, cell in enumerate(col_a, start=1):
        try:
            cell_date = datetime.strptime(cell.strip(), "%m/%d/%Y").date()
            if cell_date == today:
                return i
        except ValueError:
            continue
    return None


def update_sheet(results: list[GameResult], today: date) -> None:
    """
    Write scores and averages to the spreadsheet.

    - If today already has a row: update only the average columns (in case
      averages have shifted since the scores were recorded).
    - If today is a new day: append a fresh row with all values.
    """
    if len(results) != len(SHEET_COLUMNS):
        raise ValueError(
            f"Expected {len(SHEET_COLUMNS)} game results, got {len(results)}"
        )

    # No-leading-zero date string (M/D/YYYY) compatible with Windows and Linux
    today_str = f"{today.month}/{today.day}/{today.year}"

    ws = _open_worksheet()
    existing_row = _find_today_row(ws, today_str, today)

    if existing_row:
        logger.info(f"Row {existing_row} already exists for {today_str} — updating scores and averages")
        _update_row(ws, existing_row, today, results)
    else:
        logger.info(f"Appending new row for {today_str}")
        _append_row(ws, today_str, today, results)


def _build_row_values(today_str: str, today: date, results: list[GameResult]) -> list:
    """Build a 16-element list: [date, B, C, D, E, …, N, O, day_of_week]."""
    # Pre-fill with empty strings (16 columns: A through P)
    row = [""] * 16
    row[0]  = today_str                   # Column A: date
    row[15] = today.strftime("%A")        # Column P: day of week

    for result, (score_col, avg_col) in zip(results, SHEET_COLUMNS):
        score_idx = _col_idx(score_col)
        avg_idx   = _col_idx(avg_col)
        row[score_idx] = result.score or ""
        row[avg_idx]   = result.avg   or ""

    return row


def _append_row(ws: gspread.Worksheet, today_str: str, today: date, results: list[GameResult]) -> None:
    row = _build_row_values(today_str, today, results)
    ws.append_row(row, value_input_option="USER_ENTERED")
    logger.info("Row appended successfully.")


def _update_row(ws: gspread.Worksheet, row_num: int, today: date, results: list[GameResult]) -> None:
    """Overwrite score, average, and day-of-week cells in an existing row for today."""
    updates = []
    for result, (score_col, avg_col) in zip(results, SHEET_COLUMNS):
        if result.score is not None:
            updates.append({"range": f"{score_col}{row_num}", "values": [[result.score]]})
        if result.avg is not None:
            updates.append({"range": f"{avg_col}{row_num}", "values": [[result.avg]]})
    updates.append({"range": f"P{row_num}", "values": [[today.strftime("%A")]]})

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logger.info(f"Updated {len(updates)} cell(s) in row {row_num}.")
    else:
        logger.info("No values to update.")
