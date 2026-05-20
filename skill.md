---
name:  linkedin-games
description: A skill to collect your daily LinkedIn Games times and enter them into a Google Spreadsheet.
---

Run the following command to fetch today's LinkedIn Games scores and update the Google Spreadsheet:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python main.py --summary-only
```

The script will:
1. Check the spreadsheet for an existing row for today's date
2. If no row exists: fetch all 7 games and append a new row
3. If a row exists with missing scores: fetch only the games that are missing and update the row
4. If a row exists with all scores present: exit immediately with no action

## Parameters

| Flag | Behaviour |
|------|-----------|
| *(none)* | Smart mode — only fetches games with missing scores |
| `--update` | Fetch all 7 games and refresh scores + averages regardless of existing data |
| `--dry-run` | Run the check and fetch logic, print results, but do not write to the sheet |
| `--debug` | Save a screenshot + HTML dump for every page visited to `scripts/debug/<timestamp>/` |
| `--summary-only` | Suppress informational logs and print only the results table plus errors |

Flags can be combined, e.g. `--update --dry-run` to do a full fetch and preview without writing.

## Troubleshooting

If the script reports errors or missing scores, re-run with `--debug` to inspect what Playwright is retrieving:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python main.py --debug
```

If the LinkedIn session has expired, re-run the auth setup:

```
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts && python setup_auth.py
```
