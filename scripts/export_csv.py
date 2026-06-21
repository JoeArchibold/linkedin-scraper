"""
Export the JSON score store to a CSV file (stdlib only — no pandas).

JSON is the primary store (see json_writer.py); CSV is a derived view. This
script reads the JSON, lays out columns from sheet_layout.json, and writes a
fresh, fully-aligned CSV every time. Because the CSV is regenerated rather than
patched in place, there is no header-drift or column-alignment problem: the
output always matches the current layout.

Usage
-----
Export the default store next to it as .csv:

    python export_csv.py                     # scores.json -> scores.csv

Explicit paths:

    python export_csv.py --input scores.json --output out.csv

Notes
-----
- The CSV columns (and their order) come from the current layout. Games stored
  in the JSON but not present in the layout are intentionally omitted from the
  CSV view; they remain in the JSON store untouched.
- The "Date" column is formatted M/D/YYYY to match the existing sheet/CSV
  convention; records are emitted in chronological order.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from pathlib import Path

from json_writer import _read_data
from sheet_layout import Layout, load_layout
from config import DEFAULT_RESULTS_JSON, DEFAULT_RESULTS_CSV

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _format_date(iso_key: str) -> str:
    """ISO date key 'YYYY-MM-DD' -> 'M/D/YYYY' (matches the CSV/sheet style)."""
    try:
        d = date.fromisoformat(iso_key)
    except ValueError:
        return iso_key  # leave non-ISO keys as-is rather than crashing
    return f"{d.month}/{d.day}/{d.year}"


def _row_for_record(iso_key: str, rec: dict, layout: Layout) -> list[str]:
    """Build one CSV row (in layout column order) from a single JSON record."""
    games = (rec or {}).get("games", {}) or {}
    row: list[str] = []
    for col in layout.columns:
        if col.key == "date":
            row.append(_format_date(iso_key))
        elif col.key == "day_of_week":
            row.append((rec or {}).get("day_of_week", "") or "")
        elif col.game_key:
            field = col.key.rsplit(".", 1)[1]  # "score" | "avg" | "number"
            value = (games.get(col.game_key) or {}).get(field)
            row.append("" if value is None else str(value))
        else:
            row.append("")
    return row


def export_to_csv(json_path: Path, csv_path: Path) -> int:
    """Write a CSV view of the JSON store. Returns the number of data rows."""
    layout = load_layout()
    data = _read_data(json_path)

    headers = [c.header for c in layout.columns]
    rows = [_row_for_record(k, data[k], layout) for k in sorted(data)]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return len(rows)


def main() -> int:
    # Defaults follow the same precedence as a collection run:
    #   input  : --input  > layout output_json > $RESULTS_JSON > ./results.json
    #   output : --output > layout output_csv  > $RESULTS_CSV  > input.csv
    try:
        layout = load_layout()
        layout_json, layout_csv = layout.output_json, layout.output_csv
    except Exception as exc:
        logger.warning(f"Could not read sheet layout ({exc}); using env/defaults for paths.")
        layout_json = layout_csv = None

    default_json = layout_json or DEFAULT_RESULTS_JSON or (Path.cwd() / "results.json")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=None,
                        help=f"Path to the JSON store (default: {default_json}).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Path to the CSV to write (default: layout output_csv, "
                             "$RESULTS_CSV, or the input path with a .csv suffix).")
    args = parser.parse_args()

    json_path: Path = (args.input or default_json).expanduser()
    if args.output:
        csv_path = args.output.expanduser()
    elif layout_csv:
        csv_path = layout_csv
    elif DEFAULT_RESULTS_CSV:
        csv_path = DEFAULT_RESULTS_CSV
    else:
        csv_path = json_path.with_suffix(".csv")

    if not json_path.exists():
        logger.error(f"JSON store not found: {json_path}")
        return 1

    try:
        n = export_to_csv(json_path, csv_path)
    except Exception as exc:
        logger.error(f"Export failed: {exc}")
        return 1

    logger.info(f"Wrote {n} row(s) to {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
