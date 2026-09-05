"""
Push daily results.json entries to the leaderboard API (POST /api/ingest).

The local JSON store keeps the running user's own score / no_hints / no_mistakes
at the *game* level, while ``leaderboard_fetches`` holds every *other*
connection. The leaderboard API reads all players' scores from
``leaderboard_fetches``, so before posting we fold the running user's score and
badges into that map under the configured ``leaderboard_player_name``.

The endpoint is read from the LEADERBOARD_API_URL environment variable (see
.env.example). The API requires authentication, so the shared-secret bearer token
is read from LEADERBOARD_API_TOKEN and sent as ``Authorization: Bearer <token>``.
When either is unset, posting is a no-op so collection stays self-contained. A
failed push is logged as a warning and does not change the collector's exit
status — the local JSON store remains the source of truth.
"""

import json
import logging
import os
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent / ".env")

API_URL_ENV = "LEADERBOARD_API_URL"
API_TOKEN_ENV = "LEADERBOARD_API_TOKEN"
REQUEST_TIMEOUT_SECONDS = 60


def get_api_url() -> str | None:
    """Return the configured API URL, or None when unset/blank."""
    url = (os.getenv(API_URL_ENV) or "").strip()
    return url or None


def get_api_token() -> str | None:
    """Return the shared-secret bearer token, or None when unset/blank."""
    token = (os.getenv(API_TOKEN_ENV) or "").strip()
    return token or None


def build_api_payload(date_str: str, day_record: dict, player_name: str) -> dict:
    """
    Build the POST /api/ingest body for one day.

    Mirrors the mapper used by the leaderboard repo: each game's existing
    leaderboard_fetches is preserved and the running user's own game-level
    score/no_hints/no_mistakes is added under `player_name`. Games without a
    valid puzzle number are skipped (the API rejects them), logged via warnings.
    """
    games: dict = {}
    for game_key, entry in (day_record.get("games") or {}).items():
        if not entry:
            continue
        number = entry.get("number")
        if number is None or (isinstance(number, str) and not number.strip()):
            logger.warning("Skipping %s for API push: missing puzzle number.", game_key)
            continue

        fetches = dict(entry.get("leaderboard_fetches") or {})
        score = entry.get("score")
        if player_name and score is not None and str(score).strip():
            fetches[player_name] = {
                "score": score,
                "no_hints": bool(entry.get("no_hints")),
                "no_mistakes": bool(entry.get("no_mistakes")),
            }

        games[game_key] = {
            "number": number,
            "avg": entry.get("avg"),
            "avg_is_final": bool(entry.get("avg_is_final")),
            "leaderboard_fetches": fetches,
        }
    return {"date": date_str, "games": games}


def _post_json(payload: dict, api_url: str, token: str) -> None:
    """POST JSON to api_url with a bearer token, raising on transport/HTTP errors."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        status = getattr(resp, "status", resp.getcode())
        if not (200 <= status < 300):
            raise RuntimeError(f"HTTP {status} from {api_url}")


def push_day(output_path: Path, day: date, player_name: str) -> bool:
    """
    Push results.json[day] to the API.

    Never raises: a failure is logged as a warning and reported via the return
    value (True only on a successful POST), so collection continues either way.
    Returns False (and logs) when the player name, API URL, or bearer token is
    unset, the day has no data, or the POST fails.
    """
    if not player_name:
        logger.warning(
            "leaderboard_player_name is not set in config - skipping API push for %s.",
            day.isoformat(),
        )
        return False

    api_url = get_api_url()
    if not api_url:
        logger.info("%s not set - skipping API push for %s.", API_URL_ENV, day.isoformat())
        return False

    token = get_api_token()
    if not token:
        logger.warning(
            "%s not set - skipping API push for %s (the leaderboard API requires auth).",
            API_TOKEN_ENV,
            day.isoformat(),
        )
        return False

    try:
        if not output_path.exists():
            logger.warning("No results store at %s - skipping API push.", output_path)
            return False
        text = output_path.read_text(encoding="utf-8").strip()
        if not text:
            logger.warning("Empty results store at %s - skipping API push.", output_path)
            return False
        data = json.loads(text)
        record = data.get(day.isoformat()) if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Could not read %s for API push: %s", output_path, exc)
        return False

    if not record:
        logger.warning("No data for %s in %s - skipping API push.", day.isoformat(), output_path)
        return False

    payload = build_api_payload(day.isoformat(), record, player_name)
    if not payload["games"]:
        logger.warning("No pushable games for %s - skipping API push.", day.isoformat())
        return False

    try:
        _post_json(payload, api_url, token)
    except Exception as exc:
        logger.warning("Could not push %s to leaderboard API: %s", day.isoformat(), exc)
        return False

    logger.info("Pushed %s to leaderboard API (%d game(s)).", day.isoformat(), len(payload["games"]))
    return True
