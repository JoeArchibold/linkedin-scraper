---
name: linkedin-games
description: A skill to collect daily LinkedIn Games scores and write them to Google Sheets or a local CSV file.
---

Run the following command to fetch today's LinkedIn Games scores and update the configured Google Sheet with concise output:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python main.py --summary-only
```

The script uses the LinkedIn/Pacific date because LinkedIn Games reset at midnight Pacific time.

Default behavior:
1. Check the configured Google Sheet for an existing row for today's LinkedIn/Pacific date.
2. If no row exists, fetch all 7 games and append a new row.
3. If a row exists with missing scores, fetch only the missing games and update the row.
4. If a row exists with all scores present, exit with no action.
5. Print the results table. With `--summary-only`, suppress informational logs and keep only the table plus errors.

## Parameters

| Flag | Behavior |
|------|----------|
| *(none)* | Smart mode: only fetches games with missing scores |
| `--update` | Fetch all 7 games and refresh scores + averages regardless of existing data |
| `--dry-run` | Run the check and fetch logic, print results, but do not write output |
| `--debug` | Save a screenshot and HTML dump for every page visited to `scripts/debug/<timestamp>/` |
| `--show-status` | Include a Status column in the printed results table |
| `--summary-only` | Suppress informational logs and print only the results table plus errors |
| `--timezone <TZ>` | Override local timezone detection for the midnight/Pacific-date warning, e.g. `--timezone America/New_York` |
| `--csv [FILE]` | Write to a local CSV file instead of Google Sheets. If no file is provided, writes to `scripts/results.csv` |

Flags can be combined, e.g. `--update --dry-run` to do a full fetch and preview without writing.

For skill usage, prefer `--summary-only` so the output stays compact for model context.

## Troubleshooting

If the script reports errors or missing scores, re-run with `--debug` to inspect what Playwright is retrieving:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python main.py --debug
```

If the LinkedIn session has expired, or Google OAuth needs to be refreshed interactively, re-run the auth setup:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python setup_auth.py
```

Sensitive local runtime files are intentionally ignored by Git, including `scripts/auth/`, `scripts/.env`, debug dumps, and local CSV output.
