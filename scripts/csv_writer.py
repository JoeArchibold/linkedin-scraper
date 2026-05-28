"""
CSV writer for LinkedIn Games scores.

Provides the same interface as sheets_updater (get_today_state / write) but
targets a local CSV file instead of Google Sheets.

Column layout follows sheet_layout.json so the CSV stays in sync with the
spreadsheet structure. The first row of the CSV is the header line and is the
source of truth when reading/updating an existing file.
"""

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from config import GAMES
from sheet_layout import Layout, column_map_from_headers, load_layout
from linkedin_scraper import GameResult

logger = logging.getLogger(__name__)


def _today_str(today: date) -> str:
    return f"{today.month}/{today.day}/{today.year}"


def _layout_headers(layout: Layout) -> list[str]:
    return [c.header for c in layout.columns]


def _read_rows(csv_path: Path) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows). Empty lists if the file doesn't exist."""
    if not csv_path.exists():
        return [], []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _key_to_index(headers: list[str], layout: Layout) -> dict[str, int]:
    """{column_key: 0-based column index} for every layout column in `headers`."""
    return column_map_from_headers(headers, layout)


def get_csv_today_state(csv_path: Path, today: date) -> tuple[bool, list[str]]:
    """
    Returns (row_exists, missing_game_display_names).
    Only games present in the CSV's header row are considered.
    """
    layout = load_layout()
    headers, rows = _read_rows(csv_path)
    if not headers:
        return False, []

    key_to_idx = _key_to_index(headers, layout)
    date_idx = key_to_idx.get("date")
    if date_idx is None:
        return False, []

    today_str = _today_str(today)
    name_by_key = {g["key"]: g["name"] for g in GAMES}

    for row in rows:
        if len(row) <= date_idx or row[date_idx].strip() != today_str:
            continue
        missing: list[str] = []
        for game_key in layout.included_game_keys():
            score_idx = key_to_idx.get(f"{game_key}.score")
            if score_idx is None:
                continue
            if score_idx >= len(row) or not row[score_idx].strip():
                missing.append(name_by_key[game_key])
        return True, missing
    return False, []


def write_csv(results: list[GameResult], today: date, csv_path: Path) -> None:
    """Write scores and averages to the CSV file, creating it if needed."""
    layout = load_layout()
    today_str = _today_str(today)
    headers, rows = _read_rows(csv_path)

    if not headers:
        # New file: use the layout's canonical headers.
        headers = _layout_headers(layout)
        rows = []

    key_to_idx = _key_to_index(headers, layout)
    width = len(headers)

    def _build_row(existing: Optional[list[str]] = None) -> list[str]:
        row = list(existing) if existing else [""] * width
        if len(row) < width:
            row.extend([""] * (width - len(row)))

        def _put(key: str, value):
            idx = key_to_idx.get(key)
            if idx is None or value is None or value == "":
                return
            row[idx] = str(value)

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
            _put(f"{game_key}.score", r.score)
            _put(f"{game_key}.avg", r.avg)
            if r.number is not None:
                _put(f"{game_key}.number", r.number)
        return row

    date_idx = key_to_idx.get("date")
    updated = False
    if date_idx is not None:
        for i, existing in enumerate(rows):
            if len(existing) > date_idx and existing[date_idx].strip() == today_str:
                rows[i] = _build_row(existing)
                updated = True
                logger.info(f"Updated existing row for {today_str} in {csv_path.name}")
                break

    if not updated:
        rows.append(_build_row())
        logger.info(f"Appended new row for {today_str} to {csv_path.name}")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    logger.info(f"CSV saved: {csv_path}")
