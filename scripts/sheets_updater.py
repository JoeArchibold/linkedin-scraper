"""
Google Sheets updater for LinkedIn Games scores.

Uses OAuth2 (gspread + google-auth-oauthlib). On first run it opens a browser
for the one-time consent flow and caches a token in the OS credential store.
Subsequent runs are fully headless.

Column layout is driven by sheet_layout.json (parsed via sheet_layout.py).
Row 1 of the worksheet is the source of truth: this module reads the headers
and matches them against the layout, so reordering or excluding columns in
the sheet flows through automatically.
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
    GAMES,
    SPREADSHEET_ID,
    WORKSHEET_NAME,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
)
from auth_store import (
    GOOGLE_TOKEN_KEY,
    get_google_token_json,
    import_json_file_if_missing,
    save_google_token_json,
)
from sheet_layout import Layout, column_map_from_headers, load_layout
from linkedin_scraper import GameResult

logger = logging.getLogger(__name__)

# `drive.file` is a non-sensitive scope: it only grants access to files this
# app creates, which is what create_sheet.py needs when calling gc.create().
# Existing tokens scoped to `spreadsheets` alone will trigger a re-consent on
# next run; daily runs that only read/write existing sheets are unaffected.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    """Return valid OAuth2 credentials, refreshing or re-authorising as needed."""
    creds: Optional[Credentials] = None

    imported = import_json_file_if_missing(GOOGLE_TOKEN_KEY, GOOGLE_TOKEN_FILE)
    if imported:
        logger.info("Imported legacy Google token file into the encrypted store.")

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

        save_google_token_json(creds.to_json())
        logger.info("Google token saved to the encrypted store.")

    return creds


# ── Worksheet helpers ─────────────────────────────────────────────────────────

def _open_worksheet() -> gspread.Worksheet:
    creds = _get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(WORKSHEET_NAME)


def _column_map(ws: gspread.Worksheet, layout: Layout) -> dict[str, str]:
    """{column_key: A1_letter} for every layout column found in row 1."""
    headers = ws.row_values(1)
    mapping = column_map_from_headers(headers, layout)
    if not mapping:
        raise RuntimeError(
            f"No layout columns matched the headers in worksheet "
            f"'{ws.title}'. Either the sheet is empty or the headers don't "
            "match sheet_layout.json. Run create_sheet.py to bootstrap a new "
            "sheet, or update sheet_layout.json to match the existing one."
        )
    return mapping


def _find_today_row(ws: gspread.Worksheet, today: date, date_letter: str) -> Optional[int]:
    """Return 1-based row index of today's row in the date column, else None."""
    col_idx = ord(date_letter.upper()) - ord("A") + 1  # gspread is 1-based
    for i, cell in enumerate(ws.col_values(col_idx), start=1):
        if i == 1:
            continue  # skip header
        try:
            if datetime.strptime(cell.strip(), "%m/%d/%Y").date() == today:
                return i
        except ValueError:
            continue
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_today_state(today: date) -> tuple[Optional[int], list[str]]:
    """
    Check the spreadsheet for today's row.

    Returns (row_num, missing_game_names):
      - row_num is None if no row exists for today.
      - missing_game_names is the display names of games whose score cell in
        today's row is blank. Only games that have a column in the sheet are
        considered; excluded games never appear.
    """
    layout = load_layout()
    ws = _open_worksheet()
    col_map = _column_map(ws, layout)

    date_letter = col_map.get("date")
    if not date_letter:
        raise RuntimeError(
            f"Worksheet '{ws.title}' has no 'Date' column matching the layout."
        )

    row_num = _find_today_row(ws, today, date_letter)
    if row_num is None:
        return None, []

    row_values = ws.row_values(row_num)
    name_by_key = {g["key"]: g["name"] for g in GAMES}

    missing: list[str] = []
    for game_key in layout.included_game_keys():
        score_letter = col_map.get(f"{game_key}.score")
        if not score_letter:
            continue
        idx = ord(score_letter.upper()) - ord("A")
        if idx >= len(row_values) or not row_values[idx].strip():
            missing.append(name_by_key[game_key])
    return row_num, missing


def update_sheet(results: list[GameResult], today: date) -> None:
    """Write scores and averages to the spreadsheet for `today`."""
    layout = load_layout()
    ws = _open_worksheet()
    col_map = _column_map(ws, layout)

    date_letter = col_map.get("date")
    if not date_letter:
        raise RuntimeError("Layout has no 'Date' index column — cannot place row.")

    row_num = _find_today_row(ws, today, date_letter)
    today_str = f"{today.month}/{today.day}/{today.year}"

    if row_num:
        logger.info(f"Row {row_num} already exists for {today_str} — updating cells")
        _update_existing_row(ws, col_map, row_num, today, today_str, results, layout)
    else:
        logger.info(f"Appending new row for {today_str}")
        _append_new_row(ws, col_map, today, today_str, results, layout)


def _build_updates_for_results(
    col_map: dict[str, str],
    results: list[GameResult],
    layout: Layout,
    row_num: int,
) -> list[dict]:
    """A1 batch_update payload entries for one row's game cells."""
    updates: list[dict] = []
    result_by_name = {r.name: r for r in results}

    for game_key in layout.included_game_keys():
        game_name = next((g["name"] for g in GAMES if g["key"] == game_key), None)
        if not game_name:
            continue
        r = result_by_name.get(game_name)
        if r is None:
            continue

        if r.score is not None and (letter := col_map.get(f"{game_key}.score")):
            updates.append({"range": f"{letter}{row_num}", "values": [[r.score]]})
        if r.avg is not None and (letter := col_map.get(f"{game_key}.avg")):
            updates.append({"range": f"{letter}{row_num}", "values": [[r.avg]]})
        if r.number is not None and (letter := col_map.get(f"{game_key}.number")):
            updates.append({"range": f"{letter}{row_num}", "values": [[r.number]]})
    return updates


def _update_existing_row(
    ws: gspread.Worksheet,
    col_map: dict[str, str],
    row_num: int,
    today: date,
    today_str: str,
    results: list[GameResult],
    layout: Layout,
) -> None:
    updates = _build_updates_for_results(col_map, results, layout, row_num)

    if (letter := col_map.get("day_of_week")):
        updates.append({"range": f"{letter}{row_num}", "values": [[today.strftime("%A")]]})

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logger.info(f"Updated {len(updates)} cell(s) in row {row_num}.")
    else:
        logger.info("No values to update.")


def _append_new_row(
    ws: gspread.Worksheet,
    col_map: dict[str, str],
    today: date,
    today_str: str,
    results: list[GameResult],
    layout: Layout,
) -> None:
    # Build a full-width row covering every layout column, populating cells we
    # have data for and leaving others blank.
    width = len(layout.columns)
    row: list[str] = [""] * width

    def _put(key: str, value):
        letter = col_map.get(key)
        if not letter or value is None:
            return
        idx = ord(letter.upper()) - ord("A")
        if idx < width:
            row[idx] = value

    _put("date", today_str)
    _put("day_of_week", today.strftime("%A"))

    result_by_name = {r.name: r for r in results}
    for game_key in layout.included_game_keys():
        game_name = next((g["name"] for g in GAMES if g["key"] == game_key), None)
        if not game_name:
            continue
        r = result_by_name.get(game_name)
        if r is None:
            continue
        _put(f"{game_key}.score", r.score or "")
        _put(f"{game_key}.avg", r.avg or "")
        if r.number is not None:
            _put(f"{game_key}.number", r.number)

    ws.append_row(row, value_input_option="USER_ENTERED")
    logger.info("Row appended successfully.")
