"""
JSON-driven sheet layout.

A layout file (`sheet_layout.json` by default) declares:
  - which non-game "index" columns appear before and after the game columns
  - which games are included, and in what order
  - whether each game writes a puzzle-number column in addition to score/avg
  - the spreadsheet title and worksheet name used by create_sheet.py

The same layout drives create_sheet.py (which creates fresh spreadsheets with
appropriate headers/formatting) and sheets_updater.py / csv_writer.py (which
look up columns by header so reordering or exclusions Just Work).

Column key naming (canonical, used by callers):
  - "date", "day_of_week"             (index columns)
  - "<game_key>.score"                (always present per included game)
  - "<game_key>.avg"                  (always present per included game)
  - "<game_key>.number"               (only if include_puzzle_numbers is true)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import GAMES, SHEET_LAYOUT_FILE

# ── Built-in non-game columns ─────────────────────────────────────────────────

INDEX_COLUMNS: dict[str, dict[str, str]] = {
    "date":        {"header": "Date",        "kind": "date"},
    "day_of_week": {"header": "Day of Week", "kind": "text"},
}


@dataclass
class ColumnSpec:
    key: str                       # canonical key (see module docstring)
    header: str                    # text written to row 1
    kind: str                      # "date" | "text" | "time" | "guesses" | "number"
    game_key: Optional[str] = None # set for game columns; None for index columns


@dataclass
class Layout:
    title: str
    worksheet_name: str
    include_puzzle_numbers: bool
    columns: list[ColumnSpec]
    raw: dict = field(default_factory=dict)

    def included_game_keys(self) -> list[str]:
        """Game keys present in the layout, in column order."""
        seen: list[str] = []
        for c in self.columns:
            if c.game_key and c.game_key not in seen:
                seen.append(c.game_key)
        return seen

    def included_game_names(self) -> list[str]:
        by_key = {g["key"]: g["name"] for g in GAMES}
        return [by_key[k] for k in self.included_game_keys()]


# ── Loading ───────────────────────────────────────────────────────────────────

def _game_by_key(key: str) -> dict:
    for g in GAMES:
        if g.get("key") == key:
            return g
    raise ValueError(
        f"Layout references unknown game key: {key!r}. "
        f"Valid keys: {[g['key'] for g in GAMES]}"
    )


def _game_columns(game: dict, include_number: bool) -> list[ColumnSpec]:
    name = game["name"]
    key = game["key"]
    is_time = game["is_time"]

    cols: list[ColumnSpec] = []
    if include_number:
        cols.append(ColumnSpec(
            key=f"{key}.number",
            header=f"{name} #",
            kind="number",
            game_key=key,
        ))
    score_header = f"{name} Time" if is_time else f"{name} Guesses"
    score_kind = "time" if is_time else "guesses"
    cols.append(ColumnSpec(
        key=f"{key}.score",
        header=score_header,
        kind=score_kind,
        game_key=key,
    ))
    cols.append(ColumnSpec(
        key=f"{key}.avg",
        header=f"{name} Avg",
        kind=score_kind,
        game_key=key,
    ))
    return cols


def _index_column(idx_key: str) -> ColumnSpec:
    if idx_key not in INDEX_COLUMNS:
        raise ValueError(
            f"Unknown index column: {idx_key!r}. "
            f"Valid keys: {list(INDEX_COLUMNS)}"
        )
    meta = INDEX_COLUMNS[idx_key]
    return ColumnSpec(key=idx_key, header=meta["header"], kind=meta["kind"])


def load_layout(path: Path | None = None) -> Layout:
    """Load and validate a layout file. Falls back to SHEET_LAYOUT_FILE."""
    path = Path(path) if path else SHEET_LAYOUT_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Sheet layout file not found: {path}\n"
            "Copy sheet_layout.json from the repo or run create_sheet.py "
            "after writing one."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    include_numbers = bool(data.get("include_puzzle_numbers", False))

    columns: list[ColumnSpec] = []
    for idx_key in data.get("index_prefix", []):
        columns.append(_index_column(idx_key))

    for game_key in data.get("games", []):
        columns.extend(_game_columns(_game_by_key(game_key), include_numbers))

    for idx_key in data.get("index_suffix", []):
        columns.append(_index_column(idx_key))

    if not columns:
        raise ValueError(f"Layout {path} produced no columns")

    return Layout(
        title=data.get("title", "LinkedIn Games Tracking"),
        worksheet_name=data.get("worksheet_name", "Sheet1"),
        include_puzzle_numbers=include_numbers,
        columns=columns,
        raw=data,
    )


# ── A1 helpers ────────────────────────────────────────────────────────────────

def col_letter(idx: int) -> str:
    """0-based column index -> A1 letter (A, B, ..., Z, AA, AB, ...)."""
    if idx < 0:
        raise ValueError(idx)
    s = ""
    n = idx + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def layout_letters(layout: Layout) -> dict[str, str]:
    """Map column key -> A1 letter, based solely on the layout's declared order."""
    return {c.key: col_letter(i) for i, c in enumerate(layout.columns)}


# ── Header-driven mapping (for the live sheet) ────────────────────────────────

def _norm(header: str) -> str:
    """Aggressive normalization: strip case and all non-alphanumerics."""
    return re.sub(r"[^a-z0-9]", "", header.lower())


def column_map_from_headers(headers: list[str], layout: Layout) -> dict[str, str]:
    """
    Match a sheet's row-1 headers against the layout and return
    {column_key: A1_letter} for every match. Columns absent from the sheet are
    silently omitted, which means callers naturally skip them.

    The matcher is tolerant of casing, punctuation, and whitespace variants
    (so existing sheets with headers like "Zip time" or "Zip Avg." match
    canonical "Zip Time" / "Zip Avg").
    """
    norm_to_letter: dict[str, str] = {}
    for i, h in enumerate(headers):
        if not h:
            continue
        norm = _norm(h)
        if norm and norm not in norm_to_letter:
            norm_to_letter[norm] = col_letter(i)

    mapping: dict[str, str] = {}
    for col in layout.columns:
        letter = norm_to_letter.get(_norm(col.header))
        if letter is None and col.key.endswith(".avg"):
            # Legacy variant: some sheets use "<Name> Avg." (with period) or
            # "<Name> Average". Normalization handles the period; try the
            # spelled-out form just in case.
            game_name = next(
                (g["name"] for g in GAMES if g["key"] == col.game_key), None
            )
            if game_name:
                letter = norm_to_letter.get(_norm(f"{game_name} Average"))
        if letter is not None:
            mapping[col.key] = letter
    return mapping
