"""
JSON-driven CSV column layout.

`sheet_layout.json` declares:
  - `games`: which games to include, in column order
  - `include_puzzle_numbers`: whether to add a "<Game> #" column per game
  - `include_day_of_week`: whether to add a "Day of Week" column
  - `output_json` (optional): path to the JSON store to write
  - `output_csv` (optional): path for the exported CSV view

`output_json`/`output_csv` let a deployment declare its paths here instead of in
`.env`. Relative paths resolve against the layout file's directory. Precedence
is: CLI flag > layout file > $RESULTS_JSON/$RESULTS_CSV > built-in default.

The first column is always `Date`. If `include_day_of_week` is true, `Day of
Week` is the second column. Game columns follow in `games` order; each game
produces `[#,] score, avg` cells.

Internal column key naming used by callers:
  - "date", "day_of_week"
  - "<game_key>.score", "<game_key>.avg", "<game_key>.number"
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import GAMES, SHEET_LAYOUT_FILE

logger = logging.getLogger(__name__)


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
    output_json: Optional[Path] = None  # JSON store path declared in the layout;
                                        # None = fall back to $RESULTS_JSON/default
    output_csv: Optional[Path] = None   # CSV export path declared in the layout;
                                        # None = fall back to $RESULTS_CSV/default
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


def _resolve_layout_path(value: object, base_dir: Path, field_name: str) -> Optional[Path]:
    """
    Resolve an output-path value from the layout file.

    Returns None when unset. A relative path is resolved against `base_dir`
    (the layout file's directory), so paths declared in the layout are portable
    regardless of the current working directory the script is run from.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string path, got {value!r}"
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


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

    # Deduplicate the games list while preserving first-seen order. A duplicate
    # game key (easy to introduce by hand and hard to spot in review) would
    # otherwise emit duplicate columns. We flag it loudly but keep going, so a
    # stray copy never silently corrupts the layout.
    raw_keys = list(data.get("games", []))
    included_keys: list[str] = []
    duplicates: list[str] = []
    for game_key in raw_keys:
        if game_key in included_keys:
            duplicates.append(game_key)
            continue
        included_keys.append(game_key)
    if duplicates:
        logger.warning(
            "Duplicate game(s) in %s 'games' list were ignored: %s. "
            "Remove the extra entr%s to silence this warning.",
            path,
            ", ".join(sorted(set(duplicates))),
            "y" if len(set(duplicates)) == 1 else "ies",
        )

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

    # Output paths may be declared in the layout so a deployment needs no .env.
    # Relative paths resolve against the layout file's directory (see helper).
    base_dir = path.parent
    output_json = _resolve_layout_path(data.get("output_json"), base_dir, "output_json")
    output_csv = _resolve_layout_path(data.get("output_csv"), base_dir, "output_csv")

    return Layout(
        include_puzzle_numbers=include_numbers,
        include_day_of_week=include_dow,
        columns=columns,
        anchor_game=anchor,
        output_json=output_json,
        output_csv=output_csv,
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
