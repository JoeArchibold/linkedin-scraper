"""
LinkedIn Games daily score collector (CSV-only build).

Usage:
    python main.py              # smart mode: skip games already recorded today
    python main.py --update     # fetch all games and refresh scores + averages
    python main.py --dry-run    # print what would be written without touching the CSV
    python main.py --debug      # save a screenshot + HTML dump for every page visited
    python main.py --summary-only  # print only the results table plus errors
    python main.py --timezone America/Chicago  # override auto-detected local timezone
    python main.py --output path/to/scores.csv # write to a specific CSV file
"""

import argparse
import logging
import sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from tzlocal import get_localzone
    _TZLOCAL_AVAILABLE = True
except ImportError:
    _TZLOCAL_AVAILABLE = False

from linkedin_scraper import fetch_all_scores, GameResult
from csv_writer import get_csv_today_state, write_csv
from json_writer import get_json_today_state, write_json
from sheet_layout import load_layout
from config import DEFAULT_OUTPUT_PATH, SCRIPTS_DIR

# LinkedIn games reset at midnight Pacific time
_LINKEDIN_TZ = ZoneInfo("America/Los_Angeles")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"


def _get_linkedin_date(local_tz_name: str | None) -> date:
    """
    Return the current date in LinkedIn's timezone (America/Los_Angeles).

    Also logs a warning if the user's local date is ahead of the LinkedIn date,
    which means the games haven't reset yet even though it's a new local day.
    """
    now = datetime.now(tz=ZoneInfo("UTC"))
    linkedin_date = now.astimezone(_LINKEDIN_TZ).date()

    # Determine local timezone for the mismatch warning
    local_tz = None
    if local_tz_name:
        try:
            local_tz = ZoneInfo(local_tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{local_tz_name}' — ignoring, using auto-detect.")
    if local_tz is None and _TZLOCAL_AVAILABLE:
        local_tz = get_localzone()

    if local_tz is not None:
        local_date = now.astimezone(local_tz).date()
        if local_date > linkedin_date:
            logger.warning(
                f"It is past midnight in your local timezone ({local_tz}) "
                f"but the LinkedIn games haven't reset yet (still {linkedin_date} Pacific). "
                "Scores will be recorded under the current LinkedIn date."
            )

    return linkedin_date


def _to_seconds(value: str) -> float:
    """Convert 'M:SS' or a plain integer string to a numeric value."""
    if ":" in value:
        m, s = value.split(":")
        return int(m) * 60 + int(s)
    return float(value)


def _colorize(score: str, avg: str) -> str:
    """Wrap score in a colour code based on comparison to avg (lower is better)."""
    try:
        s, a = _to_seconds(score), _to_seconds(avg)
        if s < a:
            return f"{GREEN}{score}{RESET}"
        if s > a:
            return f"{RED}{score}{RESET}"
    except ValueError:
        pass
    return score


def print_results(results: list[GameResult], show_status: bool = False) -> None:
    """Pretty-print results to the console."""
    print()
    header = f"{'Game':<22} {'Score':<10} {'Today\'s Avg':<10}" + (" Status" if show_status else "")
    print(header)
    print("-" * len(header))
    for r in results:
        name = f"{r.name} #{r.number}" if r.number else r.name
        avg  = r.avg or "—"
        if r.score and r.avg:
            colored = _colorize(r.score, r.avg)
            # Pad manually since ANSI codes add non-printing characters
            score_col = colored + " " * max(0, 10 - len(r.score))
        elif r.score:
            score_col = f"{r.score:<10}"
        else:
            score_col = f"{'—':<10}"
        row = f"{name:<22} {score_col} {avg:<10}"
        if show_status:
            status = f"ERROR: {r.error}" if r.error else ("ok" if r.score else "skipped")
            row += status
        print(row)
    pacific_now = datetime.now(_LINKEDIN_TZ)
    print("-" * len(header))
    print(f"Updated at:{pacific_now.strftime('%I:%M %p %Z %A, %B %d %Y')}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch LinkedIn Games scores and append them to a local CSV file")
    parser.add_argument("--update",      action="store_true", help="Fetch all games and update scores + averages regardless of existing data")
    parser.add_argument("--dry-run",     action="store_true", help="Print scores without writing to the CSV")
    parser.add_argument("--debug",       action="store_true", help="Save a screenshot + HTML dump for every page visited")
    parser.add_argument("--show-status", action="store_true", help="Include a Status column in the results table")
    parser.add_argument("--summary-only", action="store_true",
                        help="Suppress informational logs and print only the results table plus errors")
    parser.add_argument("--timezone",    metavar="TZ", default=None,
                        help="Your local IANA timezone name (e.g. America/New_York). "
                             "Auto-detected if omitted.")
    parser.add_argument("--output",      metavar="FILE", default=None,
                        help="Path to the results file. Overrides $RESULTS_JSON/$RESULTS_CSV and "
                             f"the default (currently {DEFAULT_OUTPUT_PATH}). A '.json' extension "
                             "writes the JSON store; any other extension writes CSV.")
    args = parser.parse_args()

    if args.summary_only:
        logging.getLogger().setLevel(logging.ERROR)

    linkedin_date = _get_linkedin_date(args.timezone)
    logger.info(f"Running for {linkedin_date.strftime('%A, %B %d %Y')} (LinkedIn/Pacific date)")

    # ── Debug directory ────────────────────────────────────────────────────────
    debug_dir: Path | None = None
    if args.debug:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_dir = SCRIPTS_DIR / "debug" / timestamp
        debug_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Debug mode ON — files will be saved to: {debug_dir}")
        if not args.summary_only:
            logging.getLogger().setLevel(logging.DEBUG)

    # ── Check existing data ───────────────────────────────────────────────────
    output_path = Path(args.output).expanduser() if args.output else DEFAULT_OUTPUT_PATH
    is_json = output_path.suffix.lower() == ".json"
    fmt = "JSON" if is_json else "CSV"
    logger.info(f"Output file: {output_path} ({fmt})")
    try:
        if is_json:
            row_exists, missing_games = get_json_today_state(output_path, linkedin_date)
        else:
            row_exists, missing_games = get_csv_today_state(output_path, linkedin_date)
    except Exception as exc:
        logger.error(f"Could not read {fmt} file: {exc}")
        return 1
    row_num = True if row_exists else None   # reuse same None-means-new-row logic below

    # ── Determine which games to fetch ────────────────────────────────────────
    if args.update:
        names_to_fetch: set[str] | None = None          # all games
        logger.info("--update: fetching all games")
    elif row_num is None:
        names_to_fetch = None                           # no row yet — fetch all
        logger.info("No row for today — fetching all games")
    elif not missing_games:
        logger.info("All games already recorded for today. Nothing to do.")
        logger.info("Use --update to refresh scores and averages anyway.")
        return 0
    else:
        names_to_fetch = set(missing_games)
        logger.info(f"Fetching {len(missing_games)} game(s) with missing scores: {', '.join(missing_games)}")

    # ── Fetch ──────────────────────────────────────────────────────────────────
    try:
        anchor_name = load_layout().anchor_game_name()
    except Exception as exc:
        logger.warning(f"Could not read anchor_game from layout ({exc}); using default.")
        anchor_name = None

    try:
        results = fetch_all_scores(
            names=names_to_fetch,
            debug_dir=debug_dir,
            anchor_name=anchor_name,
        )
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    print_results(results, show_status=args.show_status)

    fetched  = [r for r in results if r.score is not None]
    unplayed = [r.name for r in results if r.score is None and r.error is None and r.unplayed]
    skipped  = [r.name for r in results if r.score is None and r.error is None and not r.unplayed]
    errors   = [r.name for r in results if r.error]

    if unplayed:
        logger.info(f"Not yet played today: {', '.join(unplayed)}")
    if skipped:
        logger.info(f"Skipped (already recorded): {', '.join(skipped)}")
    if errors:
        logger.warning(f"Errors fetching: {', '.join(errors)}")

    if not fetched:
        logger.warning("No new scores retrieved — output not updated.")
        return 0

    if args.dry_run:
        logger.info("Dry run — output not updated.")
        return 0

    # ── Write results ──────────────────────────────────────────────────────────
    logger.info(f"Writing to {fmt}: {output_path} …")
    try:
        if is_json:
            write_json(results, linkedin_date, output_path)
        else:
            write_csv(results, linkedin_date, output_path)
    except Exception as exc:
        logger.error(f"{fmt} write failed: {exc}")
        return 1

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
