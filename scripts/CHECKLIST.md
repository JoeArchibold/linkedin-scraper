# Update Logic Checklist

- [ ] Add a `--refresh` mode to re-fetch and overwrite scores as well as averages for the current LinkedIn date.
- [ ] Decide whether `--refresh` should replace `--update` or exist alongside it with narrower semantics.
- [ ] Optionally add plausibility checks during update flows to detect clearly incorrect existing score values before deciding whether to overwrite them.
- [ ] Harden date row lookup so it can still find today's row if column `A` was reformatted manually in Google Sheets.
- [ ] Decide how to handle duplicate rows for the same date if a user edits the sheet manually or appends inconsistent data.
- [ ] Add validation that the game results being written still match the expected game-to-column mapping, even if the scraper output order changes later.
- [ ] Resolve the docstring mismatch in `update_sheet()` so the comments clearly reflect the intended average-changing behavior for existing rows.
- [ ] Consider whether blank or failed scrape results during a refresh flow should leave existing cells untouched or explicitly flag/clear them.

## Intentional Current Behavior

- [x] In normal mode, existing scores for the current date are treated as authoritative and do not need to be rewritten.
- [x] In normal mode, `--update` is intended primarily to refresh averages, since LinkedIn averages can drift upward over the course of the day.
- [x] The spreadsheet is currently assumed to be managed by this tool on a single sheet by a single user, so some guardrails can remain deferred.
