"""
Create a fresh Google Sheets workbook (or worksheet tab) for LinkedIn Games
tracking, using sheet_layout.json as the source of truth.

Usage
-----
Create a brand-new spreadsheet from the default layout file:

    python create_sheet.py

Use an alternate layout file:

    python create_sheet.py --layout my_layout.json

Add a new worksheet tab to an existing spreadsheet instead of creating a new
workbook:

    python create_sheet.py --existing-id <spreadsheet-id>

Override the worksheet name from the layout:

    python create_sheet.py --worksheet "2027 Scores"

The script prints the new spreadsheet URL on success. It does NOT modify
`.env`; if you want main.py to write to the newly-created spreadsheet, copy
the printed ID into SPREADSHEET_ID yourself.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import gspread
from gspread.exceptions import WorksheetNotFound

from sheet_layout import ColumnSpec, Layout, layout_letters, load_layout
from sheets_updater import _get_credentials

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# ── Number-format requests per column kind ───────────────────────────────────

def _number_format_for(kind: str) -> dict | None:
    if kind == "date":
        return {"type": "DATE",   "pattern": "M/d/yyyy"}
    if kind == "time":
        return {"type": "TIME",   "pattern": "mm:ss"}
    if kind in ("guesses", "number"):
        return {"type": "NUMBER", "pattern": "0"}
    return None  # text columns get default formatting


def _build_format_requests(sheet_id: int, layout: Layout) -> list[dict]:
    """Build the Sheets API request list for header + per-column formatting."""
    requests: list[dict] = []
    n_cols = len(layout.columns)

    # 1. Freeze the header row.
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # 2. Bold + centre-align the header row.
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": n_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat(textFormat,horizontalAlignment)",
        }
    })

    # 3. Per-column number formats.
    for idx, col in enumerate(layout.columns):
        fmt = _number_format_for(col.kind)
        if fmt is None:
            continue
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,                  # skip header
                    "startColumnIndex": idx, "endColumnIndex": idx + 1,
                },
                "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                "fields": "userEnteredFormat.numberFormat",
            }
        })

    # 4. Reasonable default column widths.
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": n_cols,
            },
            "properties": {"pixelSize": 110},
            "fields": "pixelSize",
        }
    })

    return requests


# ── Spreadsheet creation ─────────────────────────────────────────────────────

def _ensure_worksheet(
    gc: gspread.Client,
    layout: Layout,
    existing_id: str | None,
    worksheet_override: str | None,
) -> tuple[gspread.Spreadsheet, gspread.Worksheet]:
    target_name = worksheet_override or layout.worksheet_name
    n_cols = len(layout.columns)

    if existing_id:
        sh = gc.open_by_key(existing_id)
        try:
            sh.worksheet(target_name)
            raise RuntimeError(
                f"Worksheet '{target_name}' already exists in spreadsheet "
                f"{existing_id}. Pick a different --worksheet name or delete "
                "the existing tab first."
            )
        except WorksheetNotFound:
            ws = sh.add_worksheet(title=target_name, rows=1000, cols=n_cols)
        logger.info(f"Added worksheet '{target_name}' to existing spreadsheet.")
    else:
        sh = gc.create(layout.title)
        ws = sh.sheet1
        if ws.title != target_name:
            ws.update_title(target_name)
        # Resize so column count matches the layout (helps formatting requests).
        ws.resize(rows=1000, cols=n_cols)
        logger.info(f"Created spreadsheet '{layout.title}'.")

    return sh, ws


def _write_headers(ws: gspread.Worksheet, columns: list[ColumnSpec]) -> None:
    headers = [c.header for c in columns]
    ws.update(values=[headers], range_name="A1", value_input_option="RAW")
    logger.info(f"Wrote {len(headers)} header(s).")


def create_sheet(
    layout: Layout,
    existing_id: str | None = None,
    worksheet_override: str | None = None,
) -> tuple[gspread.Spreadsheet, gspread.Worksheet]:
    """Create a workbook/worksheet from `layout`, write headers, apply formatting."""
    creds = _get_credentials()
    gc = gspread.authorize(creds)

    sh, ws = _ensure_worksheet(gc, layout, existing_id, worksheet_override)
    _write_headers(ws, layout.columns)

    sheet_id = ws.id
    sh.batch_update({"requests": _build_format_requests(sheet_id, layout)})
    logger.info("Applied formatting (frozen header, number formats, widths).")

    return sh, ws


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layout", type=Path, default=None,
                        help="Path to a layout JSON file (defaults to sheet_layout.json).")
    parser.add_argument("--existing-id", default=None,
                        help="Add a worksheet to this existing spreadsheet "
                             "instead of creating a new workbook.")
    parser.add_argument("--worksheet", default=None,
                        help="Override the worksheet name from the layout.")
    args = parser.parse_args()

    try:
        layout = load_layout(args.layout)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    logger.info(
        f"Layout: {len(layout.columns)} columns "
        f"({len(layout.included_game_keys())} game(s), "
        f"puzzle numbers {'ON' if layout.include_puzzle_numbers else 'off'})"
    )
    logger.info("Columns: " + ", ".join(c.header for c in layout.columns))

    try:
        sh, ws = create_sheet(layout, args.existing_id, args.worksheet)
    except Exception as exc:
        logger.error(f"Sheet creation failed: {exc}")
        return 1

    print()
    print(f"Spreadsheet URL : {sh.url}")
    print(f"Spreadsheet ID  : {sh.id}")
    print(f"Worksheet       : {ws.title}")
    print()
    print("Next steps:")
    print(f"  1. Share the spreadsheet with anyone else who needs access.")
    print(f"  2. Update scripts/.env if you want main.py to write to this sheet:")
    print(f"       SPREADSHEET_ID={sh.id}")
    print(f"       WORKSHEET_NAME={ws.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
