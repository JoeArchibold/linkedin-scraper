---
name: linkedin-games-data-collector
description: A skill to collect daily LinkedIn Games scores into a local JSON store (with optional CSV export).
---

## First-time setup

Before the first run, make sure dependencies are installed. **Set up a Python
virtual environment unless the user explicitly asks not to** — create a `.venv`
inside `scripts/`, install `requirements.txt` into it, and install the Playwright
Chromium browser. Then invoke `collector.py` with that venv's interpreter (e.g.
`scripts/.venv/Scripts/python` on Windows, `scripts/.venv/bin/python` on
macOS/Linux) rather than a bare `python`, so collection runs use the same
environment the dependencies were installed into. The full step-by-step
instructions (including the `playwright install chromium` step and platform
notes) are in `SETUP.md`.

The collector also requires a one-time interactive LinkedIn login via
`setup_auth.py`, which opens a visible browser for the user to log in. This step
cannot be automated — if no saved session exists yet, direct the user to run it
(see `SETUP.md`, "One-Time LinkedIn Login").

If dependencies are already installed and a session is saved, skip straight to
the run command below.

## Configuring the collector

Behavior is controlled by `scripts/config.json`. This file is created
automatically from `scripts/config.json.sample` on the first run if it doesn't
exist yet, and it is git-ignored (user-local), so edits persist and repo updates
won't overwrite it. The script runs with the shipped defaults if left as-is, but
offer to help the user tailor these fields to their preferences:

- `games` — the list of game keys to collect, in CSV column order. Reorder to
  taste, or omit games to exclude them. Valid keys: `zip`, `tango`, `queens`,
  `patches`, `mini_sudoku`, `crossclimb`, `wend`, `pinpoint`.
- `anchor_game` — used for played/unplayed detection; must be one of the keys
  present in `games`. Recommend the user set this to whichever game they play
  first each day, since its results page is the most likely to be complete on a
  fresh day. Note that `pinpoint` is a timer-safe option (it has no timer, so
  loading it can never start a timer on an unplayed game).
- `output_path` — directory the JSON store (and exported CSV) are written to.
  Recommend an absolute or `~`-based path so output location is fixed regardless
  of where the script is run from. `output_json` / `output_csv` are the bare
  filenames within it.
- `include_day_of_week` / `include_puzzle_numbers` — toggle those columns.
- `export_csv_on_run` — set `true` to regenerate the CSV automatically after
  every collection run.

See `SETUP.md` ("Settings in config.json" and "Output Location")
for the full annotated example and field reference.

## Running

Run the following command to fetch today's LinkedIn Games scores and record them in the configured JSON store with concise output:

```
cd ~/.claude/skills/linkedin-games-data-collector/scripts && python collector.py --summary-only
```

The script uses the LinkedIn/Pacific date because LinkedIn Games reset at midnight Pacific time.

Default behavior:

1. Check the configured JSON store for an existing entry for today's LinkedIn/Pacific date.
2. If no entry exists, fetch all configured games and add a new one.
3. If an entry exists with missing scores, fetch only the missing games and update it.
4. If an entry exists with all scores present, the default run makes no changes and exits; use `--update` to re-fetch and refresh scores and averages (averages drift upward over the day).
5. Print the results table. With `--summary-only`, suppress informational logs and keep only the table plus errors.

For every game played and collected, the collector also scrapes that game's **connections leaderboard** and stores the viewer's `no_hints` / `no_mistakes` badges plus a `leaderboard_fetches` map of each connection's score and badges on that game's daily entry. Connections who play later in the day won't appear until the leaderboard is fetched again — use `--sync-leaderboards` to refresh every played game's leaderboard without re-collecting scores.

The script reads played/unplayed state from a completed **anchor** game's results page (set by `anchor_game` in `config.json`) and skips unplayed games without opening them. If the anchor itself has not been played yet, the script collects nothing and exits cleanly (exit 0) to avoid starting timers on unplayed games — this is expected, not an error; re-run after the anchor game has been played.

## Parameters

| Flag                  | Behavior                                                                                                                                                                                                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| _(none)_              | Smart mode: only fetches games with missing scores                                                                                                                                                                                                                                    |
| `--update`            | Fetch all configured games and refresh scores + averages regardless of existing data                                                                                                                                                                                                  |
| `--dry-run`           | Run the check and fetch logic, print results, but do not write output                                                                                                                                                                                                                 |
| `--debug`             | Save a screenshot and HTML dump for every page visited to `scripts/debug/<timestamp>/`                                                                                                                                                                                                |
| `--show-status`       | Include a Status column in the printed results table                                                                                                                                                                                                                                  |
| `--summary-only`      | Suppress informational logs and print only the results table plus errors                                                                                                                                                                                                              |
| `--timezone <TZ>`     | Override local timezone detection for the midnight/Pacific-date warning, e.g. `--timezone America/New_York`                                                                                                                                                                           |
| `--output <FILE>`     | Override the JSON store path. Precedence: `--output` > `output_path`/`output_json` in `config.json` > `$RESULTS_JSON` in `.env` (fallback) > `./results.json`                                                                                                                         |
| `--export-csv`        | After writing the store, also regenerate the CSV view (same as `"export_csv_on_run": true` in `config.json`)                                                                                                                                                                          |
| `--csv-output <FILE>` | Path for the exported CSV; implies `--export-csv`                                                                                                                                                                                                                                     |
| `--sync-leaderboards` | Refresh connections-leaderboard data (`no_hints` / `no_mistakes` and every connection's `leaderboard_fetches`) for every game already played today, even if today's scores are complete. Loads only leaderboard pages (never results pages), so it is safe to re-run later in the day |

Flags can be combined, e.g. `--update --dry-run` to do a full fetch and preview without writing.

For skill usage, prefer `--summary-only` so the output stays compact for model context.

## Exporting to CSV

Scores are stored as JSON; `collector.py` writes the JSON store and the CSV is always a
derived view. Produce it in any of three ways:

```
# Standalone, from an already-collected store
cd ~/.claude/skills/linkedin-games-data-collector/scripts && python export_csv.py

# As part of a collection run
cd ~/.claude/skills/linkedin-games-data-collector/scripts && python collector.py --export-csv
```

Or set `"export_csv_on_run": true` in `config.json` to regenerate the CSV after
every run automatically. `export_csv.py` reads the store from the config's
`output_path`/`output_json` (then `$RESULTS_JSON`, then `./results.json`) and
writes the CSV to `output_path`/`output_csv` (then `$RESULTS_CSV`, then alongside
the JSON); use `--input` / `--output` to override. The CSV columns and their order
come from `scripts/config.json`, and the file is regenerated fresh on each run (so
it always matches the current layout). See `SETUP.md` for details.

## Troubleshooting

If the script reports errors or missing scores, re-run with `--debug` to inspect what Playwright is retrieving:

```
cd ~/.claude/skills/linkedin-games-data-collector/scripts && python collector.py --debug
```

If the LinkedIn session has expired, re-run the auth setup:

```
cd ~/.claude/skills/linkedin-games-data-collector/scripts && python setup_auth.py
```

To clear a saved session, run `python setup_auth.py --delete` (keeps the Fernet
key) or `--delete-key` (full local wipe). Note: deleting locally does **not**
revoke a compromised token — that must be done on LinkedIn (sign out the device
or change your password). See `SETUP.md` for the full security note.

The LinkedIn session state is encrypted with Fernet and stored in the user's per-OS data directory (`%LOCALAPPDATA%\linkedin-games\` on Windows). The Fernet master key lives in the OS credential store via `keyring`. Which games to collect, in what order, whether to log puzzle numbers and the day of week, and which game to use as the anchor for played/unplayed detection is controlled by `scripts/config.json`. The collector writes a JSON store at `./results.json` by default; override with `output_path` in `config.json` (preferred), `RESULTS_JSON` in `scripts/.env`, or `--output`. Generate a CSV from that store with `export_csv.py`, or set `"export_csv_on_run": true` in `config.json` to regenerate it after every run. See `SETUP.md` for details.
