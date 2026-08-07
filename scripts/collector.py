"""
LinkedIn Games daily score collector (writes a local JSON store).

Usage:
    python collector.py              # smart mode: skip games already recorded today
    python collector.py --update     # fetch all games and refresh scores + averages
    python collector.py --dry-run    # print what would be written without touching the store
    python collector.py --debug      # save a screenshot + HTML dump for every page visited
    python collector.py --summary-only  # print only the results table plus errors
    python collector.py --timezone America/Chicago  # override auto-detected local timezone
    python collector.py --output path/to/scores.json # write to a specific JSON store
    python collector.py --export-csv # also regenerate a CSV view ($RESULTS_CSV) after writing
    python collector.py --finalize   # standalone: finalize yesterday's averages and exit
    python collector.py --no-finalize  # skip auto-finalization of yesterday's averages
    python collector.py --check-finalized       # audit last 30 days for unfinalized averages
    python collector.py --check-finalized 45 --yes  # audit 45 days and finalize any gaps

Each normal run automatically finalizes yesterday's averages before collecting today:
it loads yesterday's results pages via ?gameUrn= (which show the post-midnight frozen
average) and updates avg + avg_is_final in the JSON store.  Requires viewer_member_id
in config.json.

viewer_member_id and leaderboard_query_id are both auto-discovered from a played game's
results page (no dev tools) and saved to config.json — seeded on first run and, for the
rotating leaderboard_query_id, refreshed automatically whenever LinkedIn changes it.

The CSV is a derived view, regenerated from the JSON each time. Use --export-csv to
refresh it as part of a collection run, or run export_csv.py standalone.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from tzlocal import get_localzone
    _TZLOCAL_AVAILABLE = True
except ImportError:
    _TZLOCAL_AVAILABLE = False

from linkedin_scraper import fetch_all_scores, fetch_final_averages, discover_voyager_ids, GameResult
from json_writer import get_json_today_state, write_json, get_finalizable_games, write_final_averages, read_results_data
from sheet_layout import load_layout
from config import DEFAULT_OUTPUT_PATH, DEFAULT_RESULTS_CSV, SCRIPTS_DIR, CONFIG_FILE

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


def print_results(
    results: list[GameResult],
    linkedin_date: date,
    show_status: bool = False,
    final: bool = False,
) -> None:
    """Pretty-print results to the console."""
    print()
    day_label = linkedin_date.strftime("%A, %B %d %Y")
    print(f"Results for {day_label} (LinkedIn/Pacific date)")
    if final:
        print(
            "Averages for this day are now FINAL."
        )
    else:
        print(
            "Averages for this day are currently PROVISIONAL and subject to change as more players record scores."
        )
    avg_label = "Final Avg" if final else "Today's Avg"
    header = f"{'Game':<22} {'Score':<10} {avg_label:<10}" + (" Status" if show_status else "")
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
            row_status = f"ERROR: {r.error}" if r.error else ("ok" if r.score else "skipped")
            row += row_status
        print(row)
    pacific_now = datetime.now(_LINKEDIN_TZ)
    print("-" * len(header))
    print(f"Updated at:{pacific_now.strftime('%I:%M %p %Z %A, %B %d %Y')}")
    print()


def _save_config_values(values: dict) -> None:
    """
    Persist auto-discovered values (e.g. viewer_member_id, leaderboard_query_id)
    into config.json. Only writes keys whose value differs from what's stored,
    so a no-op discovery leaves the file untouched.
    """
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        changed = {k: v for k, v in values.items() if v and data.get(k) != v}
        if not changed:
            return
        data.update(changed)
        CONFIG_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info(f"Saved to {CONFIG_FILE.name}: {', '.join(sorted(changed))}")
    except Exception as exc:
        logger.warning(f"Could not save values to config: {exc}")


def _run_finalizer(
    target_date: date,
    output_path: Path,
    viewer_member_id: str,
    debug_dir: Path | None,
) -> bool:
    """
    Finalize averages for target_date. Returns True if any averages were written.

    Loads yesterday's results pages via ?gameUrn= to capture the post-deadline
    frozen average, then upserts into the JSON store with avg_is_final=True.
    """
    finalizable = get_finalizable_games(output_path, target_date)
    if not finalizable:
        logger.info(f"All averages already finalized for {target_date} (or no data).")
        return False

    logger.info(f"Finalizing {len(finalizable)} game(s) from {target_date} …")

    try:
        finals = fetch_final_averages(finalizable, viewer_member_id, debug_dir)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return False
    except Exception as exc:
        logger.error(f"Finalization fetch failed: {exc}")
        return False

    finalized = [r for r in finals if r.avg is not None]
    if not finalized:
        logger.warning("No averages retrieved during finalization — store not updated.")
        return False

    try:
        count = write_final_averages(finals, target_date, output_path)
    except Exception as exc:
        logger.error(f"Failed to write final averages: {exc}")
        return False

    print_results(finals, target_date, final=True)
    logger.info(f"Finalization complete: {count} game(s) updated for {target_date}.")
    return True


def _resolve_csv_path(args, layout, output_path: Path) -> Path:
    """CSV destination precedence: --csv-output > config file > $RESULTS_CSV > JSON path .csv."""
    if args.csv_output:
        return Path(args.csv_output).expanduser()
    return layout.output_csv or (DEFAULT_RESULTS_CSV or output_path.with_suffix(".csv"))


def _export_csv_if_requested(args, layout, output_path: Path) -> None:
    """Regenerate the CSV view when --export-csv/--csv-output or export_csv_on_run is set."""
    if not (args.export_csv or args.csv_output or layout.export_csv_on_run):
        return
    from export_csv import export_to_csv
    try:
        export_to_csv(output_path, _resolve_csv_path(args, layout, output_path))
    except Exception as exc:
        logger.error(f"CSV export failed: {exc}")


def _scan_unfinalized(output_path: Path, end_date: date, days: int) -> list[tuple[date, int]]:
    """
    Return [(date, pending_game_count)] for days in the `days`-day window ending
    at end_date (inclusive) that hold scored games not yet finalized — oldest
    first. Days with no data (or already fully finalized) are omitted.
    """
    found: list[tuple[date, int]] = []
    for offset in range(days - 1, -1, -1):
        d = end_date - timedelta(days=offset)
        pending = get_finalizable_games(output_path, d)
        if pending:
            found.append((d, len(pending)))
    return found


def _run_check_finalized(
    args,
    layout,
    output_path: Path,
    linkedin_date: date,
    viewer_member_id: str,
    debug_dir: Path | None,
) -> int:
    """
    Audit the last N days for averages that were never finalized (e.g. days
    collected with --update, which skips auto-finalization) and optionally go
    back and finalize them. Standalone: does not collect today.
    """
    days = args.check_finalized
    if days < 1:
        logger.error(f"--check-finalized range must be >= 1 (got {days}).")
        return 1

    # Today's average hasn't frozen yet, so the newest finalizable day is yesterday.
    end_date = linkedin_date - timedelta(days=1)
    logger.info(f"Auditing finalized status for the {days} day(s) ending {end_date} …")

    unfinalized = _scan_unfinalized(output_path, end_date, days)
    if not unfinalized:
        logger.info("All days in range are finalized. Nothing to do.")
        return 0

    print()
    print(f"Unfinalized day(s) found ({len(unfinalized)}):")
    for d, n in unfinalized:
        print(f"  {d.isoformat()}   {n} game(s) pending")
    print()

    proceed = args.yes
    if not proceed and sys.stdin.isatty():
        try:
            proceed = input(
                f"Finalize these {len(unfinalized)} day(s) now? [y/N]: "
            ).strip().lower() in ("y", "yes")
        except EOFError:
            proceed = False

    if not proceed:
        print("Not finalized. Re-run with --yes to finalize, or target days individually:")
        for d, _ in unfinalized:
            print(f"  python collector.py --finalize --finalize-date {d.isoformat()}")
        return 0

    # Finalization needs viewer_member_id to build gameUrns; discover if absent.
    if not viewer_member_id:
        logger.info("viewer_member_id not in config — attempting auto-discovery …")
        discovered = discover_voyager_ids()
        viewer_member_id = (discovered.get("viewer_member_id") or "").strip()
        _save_config_values(discovered)
        if not viewer_member_id:
            logger.error(
                "Could not auto-discover viewer_member_id (needs a game played today). "
                "Add it to config.json to enable finalization."
            )
            return 1

    finalized_any = False
    for d, _ in unfinalized:
        if _run_finalizer(d, output_path, viewer_member_id, debug_dir):
            finalized_any = True

    if finalized_any:
        _export_csv_if_requested(args, layout, output_path)
    logger.info("Finalization audit complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch LinkedIn Games scores and record them in a local JSON store")
    parser.add_argument("--update",      action="store_true", help="Fetch all games and update scores + averages regardless of existing data")
    parser.add_argument("--dry-run",     action="store_true", help="Print scores without writing to the store")
    parser.add_argument("--debug",       action="store_true", help="Save a screenshot + HTML dump for every page visited")
    parser.add_argument("--show-status", action="store_true", help="Include a Status column in the results table")
    parser.add_argument("--summary-only", action="store_true",
                        help="Suppress informational logs and print only the results table plus errors")
    parser.add_argument("--timezone",    metavar="TZ", default=None,
                        help="Your local IANA timezone name (e.g. America/New_York). "
                             "Auto-detected if omitted.")
    parser.add_argument("--output",      metavar="FILE", default=None,
                        help="Path to the JSON store. Overrides $RESULTS_JSON and the default "
                             f"(currently {DEFAULT_OUTPUT_PATH}).")
    parser.add_argument("--export-csv",  action="store_true",
                        help="After writing the JSON store, also regenerate a CSV view "
                             "(for Google Drive sync -> Sheets import). Destination comes "
                             "from $RESULTS_CSV, --csv-output, or the JSON path with a .csv suffix.")
    parser.add_argument("--csv-output",  metavar="FILE", default=None,
                        help="Path for the exported CSV. Implies --export-csv. Overrides "
                             f"$RESULTS_CSV (currently {DEFAULT_RESULTS_CSV}).")
    parser.add_argument("--finalize",    action="store_true",
                        help="Standalone mode: fetch frozen averages for yesterday's games "
                             "and exit (skips today's collection). Use --finalize-date to "
                             "target a specific date.")
    parser.add_argument("--finalize-date", metavar="DATE", default=None,
                        help="Target date for --finalize (YYYY-MM-DD). Defaults to yesterday "
                             "in LinkedIn/Pacific time.")
    parser.add_argument("--no-finalize", action="store_true",
                        help="Skip the automatic finalization of yesterday's averages that "
                             "runs at the start of each normal collection.")
    parser.add_argument("--check-finalized", nargs="?", type=int, const=30, default=None,
                        metavar="DAYS",
                        help="Standalone audit: scan the last DAYS days (default 30, ending "
                             "yesterday) for days whose averages were never finalized — e.g. "
                             "days collected with --update, which skips auto-finalization. "
                             "Reports them and, if run interactively (or with --yes), finalizes "
                             "them. Does not collect today.")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Assume 'yes' to confirmation prompts (e.g. for --check-finalized).")
    args = parser.parse_args()

    if args.finalize and args.update:
        logger.error("--finalize and --update are mutually exclusive.")
        return 1
    if args.finalize and args.dry_run:
        logger.error("--finalize and --dry-run are mutually exclusive.")
        return 1
    if args.check_finalized is not None and (args.finalize or args.update or args.dry_run):
        logger.error("--check-finalized cannot be combined with --finalize, --update, or --dry-run.")
        return 1

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

    # ── Load layout (drives columns, anchor, and output paths) ────────────────
    try:
        layout = load_layout()
    except Exception as exc:
        logger.error(f"Could not read config: {exc}")
        return 1

    # ── Resolve output path ───────────────────────────────────────────────────
    # Precedence: --output flag > layout file > $RESULTS_JSON/default.
    if args.output:
        output_path = Path(args.output).expanduser()
    elif layout.output_json:
        output_path = layout.output_json
    else:
        output_path = DEFAULT_OUTPUT_PATH
    logger.info(f"Output file: {output_path}")

    # ── Read existing store (shared by finalization + today's state check) ────
    try:
        results_data = read_results_data(output_path)
    except Exception as exc:
        logger.error(f"Could not read JSON store: {exc}")
        return 1

    # ── Resolve viewer_member_id (needed for finalization + leaderboard check) ─
    viewer_member_id: str = (layout.raw.get("viewer_member_id") or "").strip()

    # ── Standalone finalized-status audit (--check-finalized) ─────────────────
    if args.check_finalized is not None:
        return _run_check_finalized(
            args, layout, output_path, linkedin_date, viewer_member_id, debug_dir
        )

    # ── Finalization (standalone --finalize mode or auto at start of normal run) ─
    yesterday = linkedin_date - timedelta(days=1)
    _do_finalize = args.finalize or (not args.no_finalize and not args.update and not args.dry_run)
    if args.dry_run and not args.no_finalize and not args.update:
        logger.info("--dry-run: skipping auto-finalization of yesterday's averages.")

    if _do_finalize:
        fin_date = yesterday
        if args.finalize and args.finalize_date:
            try:
                fin_date = date.fromisoformat(args.finalize_date)
            except ValueError:
                logger.error(f"Invalid --finalize-date: {args.finalize_date!r} (expected YYYY-MM-DD)")
                return 1

        # Check early whether there's anything to finalize before discovering vmid
        finalizable_check = get_finalizable_games(output_path, fin_date)
        if finalizable_check and not viewer_member_id:
            logger.info("viewer_member_id not in config — attempting auto-discovery …")
            discovered = discover_voyager_ids()
            viewer_member_id = (discovered.get("viewer_member_id") or "").strip()
            # Seed both ids (member id + leaderboard queryId) while we're here.
            _save_config_values(discovered)
            if not viewer_member_id:
                msg = (
                    "Could not auto-discover viewer_member_id (needs a game played today). "
                    "Add it to config.json to enable finalization."
                )
                if args.finalize:
                    logger.error(msg)
                    return 1
                logger.warning(msg)

        if viewer_member_id:
            did_finalize = _run_finalizer(fin_date, output_path, viewer_member_id, debug_dir)
            if did_finalize:
                _export_csv_if_requested(args, layout, output_path)

        if args.finalize:
            logger.info("Done.")
            return 0

    # ── Check existing data ───────────────────────────────────────────────────
    try:
        row_exists, missing_games = get_json_today_state(output_path, linkedin_date)
    except Exception as exc:
        logger.error(f"Could not read JSON store: {exc}")
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
    anchor_name = layout.anchor_game_name()

    leaderboard_query_id = (layout.raw.get("leaderboard_query_id") or "").strip() or None

    # fetch_all_scores fills this from the anchor page's own traffic; we persist
    # anything new/changed afterward so config.json seeds and self-heals.
    discovered_ids: dict = {}
    try:
        results = fetch_all_scores(
            names=names_to_fetch,
            debug_dir=debug_dir,
            anchor_name=anchor_name,
            leaderboard_query_id=leaderboard_query_id,
            viewer_member_id=viewer_member_id or None,
            results_data=results_data,
            discovered=discovered_ids,
        )
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    _save_config_values(discovered_ids)

    print_results(results, linkedin_date, show_status=args.show_status)

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
    logger.info(f"Writing to JSON store: {output_path} …")
    try:
        write_json(results, linkedin_date, output_path)
    except Exception as exc:
        logger.error(f"JSON write failed: {exc}")
        return 1

    # ── Optional CSV export ────────────────────────────────────────────────────
    # Triggered by --export-csv/--csv-output, or by "export_csv_on_run": true in
    # config.json. The JSON store is already safely written above; a CSV failure
    # here is reported but does not undo that.
    if args.export_csv or args.csv_output or layout.export_csv_on_run:
        from export_csv import export_to_csv
        # CSV path precedence: --csv-output flag > config file > $RESULTS_CSV >
        # the JSON path with a .csv suffix.
        if args.csv_output:
            csv_path = Path(args.csv_output).expanduser()
        elif layout.output_csv:
            csv_path = layout.output_csv
        elif DEFAULT_RESULTS_CSV:
            csv_path = DEFAULT_RESULTS_CSV
        else:
            csv_path = output_path.with_suffix(".csv")
        logger.info(f"Exporting CSV view to: {csv_path} …")
        try:
            n = export_to_csv(output_path, csv_path)
            logger.info(f"CSV exported: {csv_path} ({n} row(s)).")
        except Exception as exc:
            logger.error(f"CSV export failed (JSON store is still saved): {exc}")
            return 1

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
