"""
JSON-driven CSV column layout.

`sheet_layout.json` declares:
  - `games`: which games to include, in column order
  - `include_puzzle_numbers`: whether to add a "<Game> #" column per game
  - `include_day_of_week`: whether to add a "Day of Week" column

The first column is always `Date`. If `include_day_of_week` is true, `Day of
Week` is the second column. Game columns follow in `games` order; each game
produces `[#,] score, avg` cells.

Internal column key naming used by callers:
  - "date", "day_of_week"
  - "<game_key>.score", "<game_key>.avg", "<game_key>.number"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import GAMES, SHEET_LAYOUT_FILE


@dataclass
class ColumnSpec:
    key: str                        # canonical key (see module docstring)
    header: str                     # text written to row 1
    kind: str                       # "date" | "text" | "time" | "guesses" | "number"
    game_key: Optional[str] = None  # set for game columns; None for index columns


@dataclass
class Layout:
    include_puzzle_numbers: bool
    include_day_of_week: bool
    columns: list[ColumnSpec]
    anchor_game: Optional[str] = None  # game key whose results page is the
                                       # preferred fallback when nothing is
                                       # recorded yet today; None = scraper
                                       # picks the first to-fetch game
    raw: dict = field(default_factory=dict)

    def anchor_game_name(self) -> Optional[str]:
        """Resolve anchor_game (a key) to its display name, or None if unset."""
        if not self.anchor_game:
            return None
        for g in GAMES:
            if g["key"] == self.anchor_game:
                return g["name"]
        return None

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


def load_layout(path: Path | None = None) -> Layout:
    """Load and validate a layout file. Falls back to SHEET_LAYOUT_FILE."""
    path = Path(path) if path else SHEET_LAYOUT_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Sheet layout file not found: {path}\n"
            "Copy the default sheet_layout.json from the repo."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    include_numbers = bool(data.get("include_puzzle_numbers", False))
    include_dow = bool(data.get("include_day_of_week", True))

    columns: list[ColumnSpec] = [
        ColumnSpec(key="date", header="Date", kind="date"),
    ]
    if include_dow:
        columns.append(ColumnSpec(key="day_of_week", header="Day of Week", kind="text"))

    included_keys = list(data.get("games", []))
    for game_key in included_keys:
        columns.extend(_game_columns(_game_by_key(game_key), include_numbers))

    if len(columns) <= (2 if include_dow else 1):
        raise ValueError(f"Layout {path} has no game columns")

    anchor = data.get("anchor_game")
    if anchor is not None:
        if not isinstance(anchor, str):
            raise ValueError(
                f"anchor_game must be a string game key, got {type(anchor).__name__}"
            )
        # Validate against known keys (uses GAMES, not just included games,
        # so a typo gets caught even if the user has temporarily excluded the
        # anchor). Enforce inclusion here too: anchoring on an excluded game
        # is almost certainly a mistake.
        _game_by_key(anchor)  # raises with a helpful message on typos
        if anchor not in included_keys:
            raise ValueError(
                f"anchor_game {anchor!r} is not present in the 'games' list. "
                "Either add it to 'games' or pick a game that is included."
            )

    return Layout(
        include_puzzle_numbers=include_numbers,
        include_day_of_week=include_dow,
        columns=columns,
        anchor_game=anchor,
        raw=data,
    )


# ── Header-driven mapping (for the live CSV) ─────────────────────────────────

def _norm(header: str) -> str:
    """Aggressive normalization: strip case and all non-alphanumerics."""
    return re.sub(r"[^a-z0-9]", "", header.lower())


def column_map_from_headers(headers: list[str], layout: Layout) -> dict[str, int]:
    """
    Match a CSV's header row against the layout and return
    {column_key: 0_based_index} for every match. Columns absent from the CSV
    are silently omitted, which lets the writer skip them.

    Tolerant of casing, punctuation, and whitespace variants.
    """
    norm_to_idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        if not h:
            continue
        norm = _norm(h)
        if norm and norm not in norm_to_idx:
            norm_to_idx[norm] = i

    mapping: dict[str, int] = {}
    for col in layout.columns:
        idx = norm_to_idx.get(_norm(col.header))
        if idx is None and col.key.endswith(".avg"):
            # Legacy "<Name> Average" spelling
            game_name = next(
                (g["name"] for g in GAMES if g["key"] == col.game_key), None
            )
            if game_name:
                idx = norm_to_idx.get(_norm(f"{game_name} Average"))
        if idx is not None:
            mapping[col.key] = idx
    return mapping
