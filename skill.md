---
name: linkedin-games
description: A skill to collect daily LinkedIn Games scores into a local JSON store (with optional CSV export).
---

Run the following command to fetch today's LinkedIn Games scores and record them in the configured JSON store with concise output:

```
cd ~/.claude/skills/Linkedin-games/scripts && python main.py --summary-only
```

The script uses the LinkedIn/Pacific date because LinkedIn Games reset at midnight Pacific time.

Default behavior:
1. Check the configured JSON store for an existing entry for today's LinkedIn/Pacific date.
2. If no entry exists, fetch all configured games and add a new one.
3. If an entry exists with missing scores, fetch only the missing games and update it.
4. If an entry exists with all scores present, check the daily averages for each game and update if necessary (the `--update` parameter on the script can be used for this).
5. Print the results table. With `--summary-only`, suppress informational logs and keep only the table plus errors.

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
| `--output <FILE>` | Override the JSON store path. Defaults to `$RESULTS_JSON` from `.env`, then `./results.json` |

Flags can be combined, e.g. `--update --dry-run` to do a full fetch and preview without writing.

For skill usage, prefer `--summary-only` so the output stays compact for model context.

## Exporting to CSV

Scores are stored as JSON; `main.py` no longer writes CSV directly. To produce a
spreadsheet-friendly CSV from the store, run:

```
cd ~/.claude/skills/Linkedin-games/scripts && python export_csv.py
```

This reads the JSON store (`$RESULTS_JSON`, else `./results.json`) and writes a
CSV alongside it. Use `--input` / `--output` to choose paths. The CSV columns and
their order come from `scripts/config.json`, and the file is regenerated
fresh on each run (so it always matches the current layout). See `SETUP.md` for
details.

## Troubleshooting

If the script reports errors or missing scores, re-run with `--debug` to inspect what Playwright is retrieving:

```
cd ~/.claude/skills/Linkedin-games/scripts && python main.py --debug
```

If the LinkedIn session has expired, re-run the auth setup:

```
cd ~/.claude/skills/Linkedin-games/scripts && python setup_auth.py
```

The LinkedIn session state is encrypted with Fernet and stored in the user's per-OS data directory (`%LOCALAPPDATA%\linkedin-games\` on Windows). The Fernet master key lives in the OS credential store via `keyring`. Which games to collect, in what order, whether to log puzzle numbers and the day of week, and which game to use as the anchor for played/unplayed detection is controlled by `scripts/config.json`. The collector writes a JSON store at `./results.json` by default; override with `output_path` in `config.json`, `RESULTS_JSON` in `scripts/.env` (deprecated), or `--output`. Generate a CSV from that store with `export_csv.py`, or set `"export_csv_on_run": true` in `config.json` to regenerate it after every run. See `SETUP.md` for details.
