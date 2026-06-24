---
name: linkedin-games
description: A skill to collect daily LinkedIn Games scores into a local JSON store (with optional CSV export).
---

Run the following command to fetch today's LinkedIn Games scores and record them in the configured JSON store with concise output:

```
cd ~/.claude/skills/Linkedin-games/scripts && python collector.py --summary-only
```

The script uses the LinkedIn/Pacific date because LinkedIn Games reset at midnight Pacific time.

Default behavior:
1. Check the configured JSON store for an existing entry for today's LinkedIn/Pacific date.
2. If no entry exists, fetch all configured games and add a new one.
3. If an entry exists with missing scores, fetch only the missing games and update it.
4. If an entry exists with all scores present, the default run makes no changes and exits; use `--update` to re-fetch and refresh scores and averages (averages drift upward over the day).
5. Print the results table. With `--summary-only`, suppress informational logs and keep only the table plus errors.

The script reads played/unplayed state from a completed **anchor** game's results page (set by `anchor_game` in `config.json`) and skips unplayed games without opening them. If the anchor itself has not been played yet, the script collects nothing and exits cleanly (exit 0) to avoid starting timers on unplayed games — this is expected, not an error; re-run after the anchor game has been played.

## Parameters

| Flag | Behavior |
|------|----------|
| *(none)* | Smart mode: only fetches games with missing scores |
| `--update` | Fetch all configured games and refresh scores + averages regardless of existing data |
| `--dry-run` | Run the check and fetch logic, print results, but do not write output |
| `--debug` | Save a screenshot and HTML dump for every page visited to `scripts/debug/<timestamp>/` |
| `--show-status` | Include a Status column in the printed results table |
| `--summary-only` | Suppress informational logs and print only the results table plus errors |
| `--timezone <TZ>` | Override local timezone detection for the midnight/Pacific-date warning, e.g. `--timezone America/New_York` |
| `--output <FILE>` | Override the JSON store path. Precedence: `--output` > `output_path`/`output_json` in `config.json` > `$RESULTS_JSON` in `.env` (deprecated) > `./results.json` |
| `--export-csv` | After writing the store, also regenerate the CSV view (same as `"export_csv_on_run": true` in `config.json`) |
| `--csv-output <FILE>` | Path for the exported CSV; implies `--export-csv` |

Flags can be combined, e.g. `--update --dry-run` to do a full fetch and preview without writing.

For skill usage, prefer `--summary-only` so the output stays compact for model context.

## Exporting to CSV

Scores are stored as JSON; `collector.py` writes the JSON store and the CSV is always a
derived view. Produce it in any of three ways:

```
# Standalone, from an already-collected store
cd ~/.claude/skills/Linkedin-games/scripts && python export_csv.py

# As part of a collection run
cd ~/.claude/skills/Linkedin-games/scripts && python collector.py --export-csv
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
cd ~/.claude/skills/Linkedin-games/scripts && python collector.py --debug
```

If the LinkedIn session has expired, re-run the auth setup:

```
cd ~/.claude/skills/Linkedin-games/scripts && python setup_auth.py
```

To clear a saved session, run `python setup_auth.py --delete` (keeps the Fernet
key) or `--delete-key` (full local wipe). Note: deleting locally does **not**
revoke a compromised token — that must be done on LinkedIn (sign out the device
or change your password). See `SETUP.md` for the full security note.

The LinkedIn session state is encrypted with Fernet and stored in the user's per-OS data directory (`%LOCALAPPDATA%\linkedin-games\` on Windows). The Fernet master key lives in the OS credential store via `keyring`. Which games to collect, in what order, whether to log puzzle numbers and the day of week, and which game to use as the anchor for played/unplayed detection is controlled by `scripts/config.json`. The collector writes a JSON store at `./results.json` by default; override with `output_path` in `config.json`, `RESULTS_JSON` in `scripts/.env` (deprecated), or `--output`. Generate a CSV from that store with `export_csv.py`, or set `"export_csv_on_run": true` in `config.json` to regenerate it after every run. See `SETUP.md` for details.
