"""
JSON-driven configuration and CSV column layout.

`config.json` declares:
  - `games`: which games to include, in column order
  - `include_puzzle_numbers`: whether to add a "<Game> #" column per game
  - `include_day_of_week`: whether to add a "Day of Week" column
  - `output_path` (optional): directory the outputs are written to. A relative
    value resolves against the current working directory; absolute paths and a
    leading `~` are honoured as-is. Defaults to the current working directory.
  - `output_json` (optional): JSON store filename within `output_path`
    (default `results.json`). A bare filename — no directory component.
  - `output_csv` (optional): exported-CSV filename within `output_path`
    (default `results.csv`). A bare filename — no directory component.
  - `export_csv_on_run` (optional): regenerate the CSV automatically after
    every collection run, without needing the --export-csv flag

`output_path`/`output_json`/`output_csv` let a deployment declare where output
goes here instead of in `.env`. Precedence is: CLI flag > config file >
$RESULTS_JSON/$RESULTS_CSV > built-in default (./results.json next to the CWD).

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

from config import GAMES, CONFIG_FILE

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
    output_json: Optional[Path] = None  # composed output_path/output_json; None
                                        # = fall back to $RESULTS_JSON/default
    output_csv: Optional[Path] = None   # composed output_path/output_csv; None
                                        # = fall back to $RESULTS_CSV/default
    export_csv_on_run: bool = False     # regenerate the CSV after every run, as
                                        # if --export-csv were always passed
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


def _resolve_output_dir(value: object) -> Optional[Path]:
    """
    Resolve the `output_path` directory, or None when unset.

    A relative value resolves against the current working directory; absolute
    paths and a leading ``~`` are honoured as-is. None means "not configured"
    (callers default the directory to the CWD).
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"output_path must be a non-empty directory path string, got {value!r}"
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _output_filename(value: object, field_name: str) -> Optional[str]:
    """
    Validate a bare output filename (output_json / output_csv), or None if unset.

    These name a file *within* `output_path`, so a value containing a directory
    separator is rejected with guidance to use output_path for the directory.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty filename string, got {value!r}")
    if "/" in value or "\\" in value or value.strip() in (".", ".."):
        raise ValueError(
            f"{field_name} must be a bare filename without a directory (got {value!r}); "
            "put the directory in output_path instead."
        )
    return value.strip()


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
    """Load and validate the config file. Falls back to CONFIG_FILE."""
    path = Path(path) if path else CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy the default config.json from the repo."
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

    # Output location: `output_path` is the directory (a relative value resolves
    # against the CWD; absolute/~ as-is; omitted => CWD), and output_json /
    # output_csv are bare filenames within it (defaulting to results.json /
    # results.csv). A stream's composed path is None — meaning "fall through to
    # $RESULTS_* / built-in default" — only when the config declares no output
    # settings for it at all. Declaring the config so a deployment needs no .env.
    output_path_raw = data.get("output_path")
    output_dir = _resolve_output_dir(output_path_raw)
    json_name = _output_filename(data.get("output_json"), "output_json")
    csv_name = _output_filename(data.get("output_csv"), "output_csv")
    has_dir = output_path_raw is not None
    base = output_dir or Path.cwd()
    output_json = base / (json_name or "results.json") if (has_dir or json_name) else None
    output_csv = base / (csv_name or "results.csv") if (has_dir or csv_name) else None
    export_csv_on_run = bool(data.get("export_csv_on_run", False))

    return Layout(
        include_puzzle_numbers=include_numbers,
        include_day_of_week=include_dow,
        columns=columns,
        anchor_game=anchor,
        output_json=output_json,
        output_csv=output_csv,
        export_csv_on_run=export_csv_on_run,
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
