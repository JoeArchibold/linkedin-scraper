"""
JSON writer for LinkedIn Games scores.

Exposes get_json_today_state / write_json (the read-state and upsert entry
points collector.py calls) and stores results in a structured JSON file. JSON is the
primary, schema-flexible store; a CSV can be exported from it on demand with
export_csv.py.

Unlike the CSV writer, there is no positional header row to keep in sync with
config.json: each daily record stores games keyed by their stable
`game_key`, so adding a game to the layout simply makes new keys appear in
future records. Records are keyed by ISO date (YYYY-MM-DD), which sorts
chronologically.

File shape:

    {
      "2026-06-10": {
        "day_of_week": "Wednesday",
        "games": {
          "zip":  {"number": "449", "score": "0:08", "avg": "0:17"},
          "wend": {"number": "1",   "score": "1:12", "avg": null}
        }
      }
    }

Writes are atomic: the file is written to a sibling temp file and then
os.replace()'d into place, so a crash mid-write cannot corrupt history.
"""

import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from config import GAMES
from sheet_layout import Layout, load_layout
from linkedin_scraper import GameResult

logger = logging.getLogger(__name__)


def _date_key(today: date) -> str:
    """ISO date key, e.g. '2026-06-10' (sorts chronologically as a string)."""
    return today.isoformat()


def _read_data(path: Path) -> dict:
    """Return the parsed JSON object, or {} if the file is absent or empty."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"{path} does not contain a JSON object keyed by date "
            f"(found {type(data).__name__})."
        )
    return data


def _ordered_for_output(data: dict, layout: Layout) -> dict:
    """
    Return a copy of `data` with dates sorted chronologically and each record's
    games emitted in layout order. Games present in a record but absent from the
    current layout (e.g. historical or excluded games) are preserved at the end
    so exporting/rewriting never drops data.
    """
    game_order = layout.included_game_keys()
    out: dict = {}
    for d in sorted(data):
        rec = data[d] or {}
        games = rec.get("games", {}) or {}
        ordered_games = {k: games[k] for k in game_order if k in games}
        for k in games:  # keep any unknown/historical games we don't recognise
            if k not in ordered_games:
                ordered_games[k] = games[k]
        out[d] = {
            "day_of_week": rec.get("day_of_week", ""),
            "games": ordered_games,
        }
    return out


def get_json_today_state(path: Path, today: date) -> tuple[bool, list[str]]:
    """
    Returns (row_exists, missing_game_display_names).

    Only games included in the current layout are considered. A game counts as
    "missing" when today's record has no non-empty score for it.
    """
    layout = load_layout()
    data = _read_data(path)
    key = _date_key(today)
    rec = data.get(key)
    if not rec:
        return False, []

    games = rec.get("games", {}) or {}
    name_by_key = {g["key"]: g["name"] for g in GAMES}

    missing: list[str] = []
    for game_key in layout.included_game_keys():
        score = (games.get(game_key) or {}).get("score")
        if not (score and str(score).strip()):
            missing.append(name_by_key[game_key])
    return True, missing


def _atomic_write(path: Path, data: dict) -> None:
    """Write `data` as pretty JSON to `path` atomically (temp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        # Clean up the temp file if anything went wrong before the replace.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json(results: list[GameResult], today: date, path: Path) -> None:
    """
    Upsert today's scores and averages into the JSON store.

    Only non-empty fields overwrite existing values, so an incremental run that
    fills in a previously-missing game leaves already-recorded games intact.
    """
    layout = load_layout()
    data = _read_data(path)
    key = _date_key(today)

    rec = data.get(key) or {}
    rec["day_of_week"] = today.strftime("%A")
    games = rec.get("games") or {}

    result_by_name = {r.name: r for r in results}
    for game_key in layout.included_game_keys():
        game_name = next((g["name"] for g in GAMES if g["key"] == game_key), None)
        if not game_name:
            continue
        r = result_by_name.get(game_name)
        if r is None:
            continue
        entry = games.get(game_key) or {}
        if r.number is not None:
            entry["number"] = r.number
        if r.score is not None:
            entry["score"] = r.score
        if r.avg is not None:
            entry["avg"] = r.avg
        if entry:
            games[game_key] = entry

    rec["games"] = games
    data[key] = rec

    _atomic_write(path, _ordered_for_output(data, layout))
    logger.info(f"JSON saved: {path}")
