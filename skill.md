---
name: linkedin-games
description: A skill to collect daily LinkedIn Games scores and write them to a local CSV file.
---

Run the following command to fetch today's LinkedIn Games scores and append them to the configured CSV file with concise output:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python main.py --summary-only
```

The script uses the LinkedIn/Pacific date because LinkedIn Games reset at midnight Pacific time.

Default behavior:
1. Check the configured CSV for an existing row for today's LinkedIn/Pacific date.
2. If no row exists, fetch all configured games and append a new row.
3. If a row exists with missing scores, fetch only the missing games and update the row.
4. If a row exists with all scores present, exit with no action.
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
| `--output <FILE>` | Override the CSV path. Defaults to `$RESULTS_CSV` from `.env`, then `./results.csv` |

Flags can be combined, e.g. `--update --dry-run` to do a full fetch and preview without writing.

For skill usage, prefer `--summary-only` so the output stays compact for model context.

## Troubleshooting

If the script reports errors or missing scores, re-run with `--debug` to inspect what Playwright is retrieving:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python main.py --debug
```

If the LinkedIn session has expired, re-run the auth setup:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python setup_auth.py
```

The LinkedIn session state is encrypted with Fernet and stored in the user's per-OS data directory (`%LOCALAPPDATA%\linkedin-games\` on Windows). The Fernet master key lives in the OS credential store via `keyring`. Which games to collect, in what order, and whether to log puzzle numbers and the day of week is controlled by `scripts/sheet_layout.json`. The output CSV location is `./results.csv` by default; override with `RESULTS_CSV` in `scripts/.env` or `--output`. See `SETUP.md` for details.
