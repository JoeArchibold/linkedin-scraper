"""
CSV writer for LinkedIn Games scores.

Provides the same interface as sheets_updater (get_today_state / write) but
targets a local CSV file instead of Google Sheets.

Column layout mirrors the spreadsheet exactly:
  Date, Zip, ZipAvg, Tango, TangoAvg, Queens, QueensAvg,
  Patches, PatchesAvg, MiniSudoku, MiniSudokuAvg,
  CrossClimb, CrossClimbAvg, Pinpoint, PinpointAvg, DayOfWeek
"""

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from config import GAMES, SHEET_COLUMNS
from linkedin_scraper import GameResult

logger = logging.getLogger(__name__)

# Header row — built from GAMES config so it stays in sync automatically
HEADERS = ["Date"]
for game in GAMES:
    col_name = game["name"].replace(" ", "")
    HEADERS += [col_name, f"{col_name}Avg"]
HEADERS.append("DayOfWeek")


def _today_str(today: date) -> str:
    return f"{today.month}/{today.day}/{today.year}"


def _read_rows(csv_path: Path) -> list[dict]:
    """Return all rows as a list of dicts, or [] if the file doesn't exist."""
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_csv_today_state(csv_path: Path, today: date) -> tuple[bool, list[str]]:
    """
    Check the CSV for today's row.

    Returns (row_exists, missing_game_names):
      - row_exists is False if no row for today is present.
      - missing_game_names lists games whose score cell is blank.
    """
    today_str = _today_str(today)
    rows = _read_rows(csv_path)

    for row in rows:
        try:
            row_date = row.get("Date", "").strip()
            if row_date == today_str:
                missing = []
                for game in GAMES:
                    col = game["name"].replace(" ", "")
                    if not row.get(col, "").strip():
                        missing.append(game["name"])
                return True, missing
        except Exception:
            continue

    return False, []


def write_csv(results: list[GameResult], today: date, csv_path: Path) -> None:
    """
    Write scores and averages to the CSV file.

    - If today already has a row: update the score/avg cells in place.
    - If today is new: append a fresh row.
    """
    today_str = _today_str(today)
    rows = _read_rows(csv_path)

    # Build the new row as a dict
    new_row: dict[str, str] = {h: "" for h in HEADERS}
    new_row["Date"]       = today_str
    new_row["DayOfWeek"]  = today.strftime("%A")

    for result, (score_col, avg_col) in zip(results, SHEET_COLUMNS):
        col_name = result.name.replace(" ", "")
        if result.score is not None:
            new_row[col_name] = result.score
        if result.avg is not None:
            new_row[f"{col_name}Avg"] = result.avg

    # Check whether today's row already exists
    updated = False
    for i, row in enumerate(rows):
        if row.get("Date", "").strip() == today_str:
            # Merge: only overwrite cells that have a new value
            for key, val in new_row.items():
                if val:
                    rows[i][key] = val
            updated = True
            logger.info(f"Updated existing row for {today_str} in {csv_path.name}")
            break

    if not updated:
        rows.append(new_row)
        logger.info(f"Appended new row for {today_str} to {csv_path.name}")

    # Re-write the whole file (CSV files don't support in-place row edits)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"CSV saved: {csv_path}")
