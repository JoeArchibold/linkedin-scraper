# Setup Guide

You can clone or copy this project anywhere on disk and run the script from
any working directory. The commands below assume you are inside the project's
`scripts/` folder; adjust paths as needed.

**To use this project as a Claude Code skill**, the project root must be
placed at `~/.claude/skills/linkedin-games-data-collector/` (so the script lives at
`~/.claude/skills/linkedin-games-data-collector/scripts/`). On Windows, `~` expands to
`%USERPROFILE%` (typically `C:\Users\<you>\.claude\skills\Linkedin-games\`).
For ad-hoc / non-skill use, any location works.

Python 3.10 or newer is required. Using a Python virtual environment (VENV) is recommended.
During development of the script, Python 3.14.2 was used.

## Setting up dependencies

The following commands can be used to set up the virtual environment, and install depdencies:

### Windows (PowerShell)

```powershell
cd path\to\Linkedin-games\scripts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### macOS / Linux (bash or zsh)

```bash
cd path/to/Linkedin-games/scripts
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

On Debian/Ubuntu you may also need `sudo apt install python3-venv` before
creating the venv, and Playwright may prompt you to install system libraries
via `playwright install-deps chromium`.

The `playwright install chromium` step downloads the Chromium browser binary
that Playwright controls. It is required on every platform.

## One-Time LinkedIn Login

Run the `setup_auth.py` script in the scripts folder and log in to LinkedIn in the browser window it opens.
A visible Chromium window appears at LinkedIn's login page. Log in normally.
Once your feed or home page has loaded, return to the terminal and press
Enter. The script encrypts your session state (cookies + localStorage) with
Fernet and writes it to the per-OS data directory described below.

After this, `collector.py` runs fully headless.

## Local Auth State

The collector creates or uses these local values:

| Location                                                                   | Purpose                                                                                                                                                                                                                                                 |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/.env`                                                             | Optional. Can set `RESULTS_JSON` / `RESULTS_CSV` output paths, though setting `output_path` in `config.json` is the preferred method (see "Output Location"). Create from `scripts/.env.example` if you want the env-based fallback.                    |
| `scripts/config.json`                                                      | Column layout and output paths. Controls which games are collected, in what order, whether to log puzzle numbers and the day of week, and (optionally) where the JSON store and exported CSV are written. Derived from config.json.sample on first run. |
| `<user data dir>/linkedin_state.enc`                                       | Fernet-encrypted Playwright storage state for LinkedIn.                                                                                                                                                                                                 |
| `<user data dir>/passphrase.salt`                                          | Created only if the passphrase fallback is used.                                                                                                                                                                                                        |
| OS credential store: `linkedin-games-data-collector` / `fernet-master-key` | Fernet key that decrypts the `.enc` file.                                                                                                                                                                                                               |

`<user data dir>` resolves per OS via `platformdirs`:

| OS      | Path                                                                                   |
| ------- | -------------------------------------------------------------------------------------- |
| Windows | `%LOCALAPPDATA%\linkedin-games\` (e.g. `C:\Users\<you>\AppData\Local\linkedin-games\`) |
| macOS   | `~/Library/Application Support/linkedin-games/`                                        |
| Linux   | `$XDG_DATA_HOME/linkedin-games/` (defaults to `~/.local/share/linkedin-games/`)        |

On POSIX systems the `.enc` file is written with mode `0600`. On Windows it
lives under `%LOCALAPPDATA%`, which is already ACL-protected for the current
user.

The master Fernet key is resolved on every run in this order:

1. `$LINKEDIN_GAMES_MASTER_KEY` environment variable, if set.
2. The OS credential store entry (created automatically on first run).
3. An interactive passphrase prompt with PBKDF2-HMAC-SHA256 (fallback for
   headless environments with no keyring backend; salt is stored beside the
   ciphertext).

## Output Location

**Set an explicit `output_path` in `scripts/config.json`.** This is the single
most important thing to configure: it pins where your data lives so it never
depends on which directory a run happens to start in (which matters a lot for
scheduled jobs). Outputs are a directory (`output_path`) plus two filenames:

```jsonc
{
  "output_path": "C:/Users/<you>/Documents/linkedin-games",
  "output_json": "results.json", // optional, default results.json
  "output_csv": "results.csv", // optional, default results.csv
  "games": [
    /* ... */
  ],
}
```

- `output_path` is the directory the JSON store and exported CSV are written to.
  **An absolute path (or one starting with `~`) is strongly recommended.** A
  _relative_ `output_path` resolves against the current working directory, and
  if you omit it entirely the directory defaults to that CWD — fine for ad-hoc
  runs, risky for scheduled ones, which is why an explicit path is preferred.
- `output_json` / `output_csv` are **bare filenames** within `output_path` (no
  directory part — a value containing a path separator is rejected). They
  default to `results.json` / `results.csv`.

The full resolution order for each path is:

|                        | JSON store                    | CSV view                       |
| ---------------------- | ----------------------------- | ------------------------------ |
| 1. CLI flag            | `--output` (full path)        | `--csv-output` (full path)     |
| 2. Config file         | `output_path` + `output_json` | `output_path` + `output_csv`   |
| 3. `.env` _(fallback)_ | `RESULTS_JSON`                | `RESULTS_CSV`                  |
| 4. Built-in default    | `./results.json` (CWD)        | JSON path with a `.csv` suffix |

> **Note:** `scripts/.env` (`RESULTS_JSON` / `RESULTS_CSV`) works as a
> lower-precedence fallback, but setting `output_path` in the config file is the
> preferred method. New setups should not need `.env` at all.
>
> Both `.env` paths and a relative `output_path` resolve against the **current
> working directory**; prefer an absolute `output_path` so the location is fixed.

> **Note:** `collector.py` writes the JSON store directly; CSV is always a derived
> view, produced on demand from the JSON either with `export_csv.py` or by adding
> `--export-csv` to a collection run (see "Exporting to CSV").

### JSON store format

The store is a single JSON object keyed by ISO date (`YYYY-MM-DD`). Each day
holds the day of week and a `games` object keyed by game id:

```jsonc
{
  "2026-06-10": {
    "day_of_week": "Wednesday",
    "games": {
      "zip": { "number": "450", "score": "0:28", "avg": "0:24" },
      "wend": { "number": "2", "score": "0:32", "avg": "1:01" },
    },
  },
}
```

Because games are keyed by id rather than by fixed columns, adding or removing a
game needs no migration — new ids simply appear in future entries, and games no
longer in the layout are preserved untouched. Writes are atomic (a temp file is
swapped into place), so an interrupted run cannot corrupt the store.

### Connections leaderboard data

For every game collected on a given day, the collector also loads that game's
**connections** leaderboard page — but only when the game was actually played,
since an unplayed game's leaderboard won't render. Each played game's daily
entry then carries three extra fields:

- `no_hints` / `no_mistakes` — booleans describing the viewer's own "You" row:
  whether they solved the puzzle without using hints and/or without making
  mistakes. A badge reading "No hints!" stores `"no_hints": true`; "No hints &
  no mistakes!" sets both true; no badge at all means both false.
- `leaderboard_fetches` — a nested object mapping every other connection's
  display name (e.g. `"Iain Hamilton"`) to that player's
  `{ "score", "no_hints", "no_mistakes" }`, in leaderboard (rank) order.

```jsonc
{
  "2026-09-03": {
    "day_of_week": "Thursday",
    "games": {
      "tango": {
        "number": "696",
        "score": "0:31",
        "avg": "1:08",
        "no_hints": true,
        "no_mistakes": true,
        "leaderboard_fetches": {
          "Iain Hamilton": {
            "score": "0:30",
            "no_hints": true,
            "no_mistakes": true,
          },
          "Madilyn Webb": {
            "score": "0:43",
            "no_hints": true,
            "no_mistakes": true,
          },
          "Alex Fong": {
            "score": "1:06",
            "no_hints": false,
            "no_mistakes": false,
          },
        },
      },
    },
  },
}
```

The leaderboard is a snapshot: connections who play _later_ in the day won't
appear until that game's leaderboard is fetched again. Re-run
`python collector.py --sync-leaderboards` (see "Command-Line Parameters" below)
to refresh it for every game already played today without touching scores,
averages, or puzzle numbers.

## Settings in config.json

The `config.json` file contains settings that allow for customizing a number of
behaviors within the script, including the anchor game (which should be whatever
game you play first on a daily basis), the order in which games will be retrieved
and displayed in CSV output, and the locations of the output files.

Note that the first time the script runs, the `config.json.sample` file will be copied
to `config.json`. If you wish to customize before running the script, make the edits there.
This is to prevent future changes to the repo from overwriting your custom configuration.

The following settings are available in this file. This is a template/reference,
not a literal copy-paste config:

```jsonc
{
  "include_day_of_week": <true|false>,    // include/ exclude the Day of Week column
  "include_puzzle_numbers": <true|false>, // include/exclude a "<Game> #" column per game
  "anchor_game": "zip",                   // the game you typically play first;
                                          // its results page is loaded first when
                                          // nothing is recorded yet today, since
                                          // it's the most likely to be complete.
                                          // Omit/null for current behavior (the
                                          // first game in 'games' is used).
  "output_path": "~/linkedin-games",      // directory the outputs are written to.
                                          // Absolute or ~ recommended. A relative
                                          // value resolves against the directory you
                                          // run from; omit to default to that CWD.
  "output_json": "results.json",          // JSON store filename within output_path
                                          // (bare filename). Default results.json.
  "output_csv": "results.csv",            // exported-CSV filename within output_path
                                          // (bare filename). Default results.csv.
  "export_csv_on_run": <true|false>,      // optional: when true, regenerate the CSV
                                          // automatically after every collection run,
                                          // as if --export-csv were always passed.
                                          // No effect on --dry-run or when no new
                                          // scores were written.
  "games": [                              //Specify the order in which games will be collected.
    "zip",                                // can be reordered to your preferences
    "tango",                              // or you can omit one or more games to exclude them
    "queens",
    "patches",
    "mini_sudoku",
    "crossclimb",
    "wend",
    "pinpoint"
  ]
}
```

Valid game keys: `zip`, `tango`, `queens`, `patches`, `mini_sudoku`,
`crossclimb`, `wend`, `pinpoint`. `anchor_game` must be one of the keys present
in `games`; otherwise startup fails with a clear error. A game listed more than
once in `games` is collected only once — the duplicate is ignored and a warning
is logged so you can remove it.

The layout controls the **exported CSV** (see "Exporting to CSV") and the order
in which game data will be collected and displayed on the script's summary table;
the JSON store itself is keyed by game id and is unaffected by column order.
The exported CSV column order is always:

```
Date, [Day of Week,] <game columns in the order specified in config.json>
```

Per game, columns are `[<Game> #,] <Game> Time-or-Guesses, <Game> Avg`.

You can change the layout at any time after results have been collected — the
JSON store needs no migration, since it stores games by id rather than by fixed
columns. The next CSV export run simply regenerates the CSV against the new
layout.

## First Run Check

After setting up authentication, the following command can be used to verify that the script is functioning correctly

```
python collector.py --dry-run --summary-only
```

This authenticates, fetches today's scores, prints the result table, and
exits without writing the store. Confirm scores look right, then run for real:

```
python collector.py
```

## Exporting to CSV

The CSV file will be generated from the data in JSON store on demand. You can produce it three ways:

```
# As part of a collection run — collect, then regenerate the CSV
python collector.py --export-csv

# Standalone, from an already-collected store
python export_csv.py

# Standalone with explicit input/output
python export_csv.py --input results.json --output scores.csv
```

To regenerate the CSV on **every** run without passing `--export-csv`, set
`"export_csv_on_run": true` in `config.json`.

Behavior and notes:

- Both `collector.py --export-csv` and `export_csv.py` resolve the CSV destination
  the same way: `--csv-output`/`--output` flag, then the config's
  `output_path`/`output_csv`, then `$RESULTS_CSV` _(fallback)_, then the JSON
  path with a `.csv` suffix. The JSON store path that `export_csv.py` reads
  follows the same precedence as `collector.py` (see "Output Location").
- Columns and their order come from `scripts/config.json`, so the CSV
  always reflects the current layout. The file is **regenerated in full** on
  each run — it is never edited in place — which avoids header drift and
  column-misalignment problems.
- The JSON store remains the source of truth; the CSV is a disposable view you
  can recreate at any time. Games present in the store but absent from the
  layout are simply omitted from the CSV (and left intact in the store).
- It is dependency-free (Python standard library only); no pandas required.

| Flag              | Behavior                                                                                                                          |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `--input <FILE>`  | JSON store to read. Defaults to the config's `output_path`/`output_json`, then `$RESULTS_JSON`, then `./results.json`.            |
| `--output <FILE>` | CSV to write. Defaults to the config's `output_path`/`output_csv`, then `$RESULTS_CSV`, then the input path with a `.csv` suffix. |

## Command-Line Parameters

`collector.py` accepts the following flags. They can be combined freely (e.g.
`--update --dry-run` for a full fetch + preview with no write).

| Flag                  | Behavior                                                                                                                                                                                                                                                                                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| _(none)_              | **Smart mode.** Reads the JSON store, looks for today's entry, and fetches only the games that are missing. If today's entry is complete, exits without touching the network. If no entry exists, fetches every configured game and adds a new one.                                                                                                           |
| `--update`            | Fetch every configured game and refresh both score and average values regardless of what's already stored. Use this when LinkedIn has corrected a score or when you want to force averages to recompute.                                                                                                                                                      |
| `--dry-run`           | Run the full fetch + check logic and print the results table, but do not write or modify the store. Useful for verifying a setup change before committing it to the file.                                                                                                                                                                                     |
| `--debug`             | Save a PNG screenshot and an HTML dump for every page Playwright visits, under `scripts/debug/<timestamp>/`. Use when scores come back wrong or missing to inspect what LinkedIn actually returned. Output is **not** auto-pruned.                                                                                                                            |
| `--show-status`       | Add a Status column to the printed results table indicating, per game, whether the score was newly fetched, already present, skipped, or errored. Does not affect stored contents.                                                                                                                                                                            |
| `--summary-only`      | Suppress informational log lines and print only the results table plus errors. Recommended when invoking from a Claude skill or any other context where compact output matters.                                                                                                                                                                               |
| `--timezone <TZ>`     | Override local-timezone auto-detection used for the "are you running near Midnight Pacific?" warning. Accepts any IANA timezone name, e.g. `America/New_York`, `Europe/London`, `Asia/Tokyo`. Does **not** change the LinkedIn/Pacific date used for the stored entry.                                                                                        |
| `--output <FILE>`     | Override the JSON store path for this run. Precedence: `--output` > `output_path`/`output_json` in `config.json` > `$RESULTS_JSON` _(fallback)_ > `./results.json`. A relative `--output` resolves against the CWD.                                                                                                                                           |
| `--export-csv`        | After writing the JSON store, also regenerate the CSV view. Destination precedence: `--csv-output` > `output_path`/`output_csv` in `config.json` > `$RESULTS_CSV` _(fallback)_ > the JSON path with a `.csv` suffix. A CSV failure is reported but does not undo the JSON write.                                                                              |
| `--csv-output <FILE>` | Path for the exported CSV. Implies `--export-csv`. Overrides the config's `output_path`/`output_csv` and `$RESULTS_CSV` for this run.                                                                                                                                                                                                                         |
| `--sync-leaderboards` | Refresh connections-leaderboard data (`no_hints` / `no_mistakes` and every connection's `leaderboard_fetches`) for every game already played today, even when today's scores are complete. Loads only each game's leaderboard page — never its results page — so it is safe to re-run any time after playing. Games with no recorded score today are skipped. |

### Common invocations

```bash
# Normal daily run — smart mode, full logs
python collector.py

# Compact output (recommended for skill / automation use)
python collector.py --summary-only

# Re-fetch everything (e.g. after LinkedIn corrected a score)
python collector.py --update

# Preview a config change without writing
python collector.py --dry-run --show-status

# Diagnose a missing or wrong score
python collector.py --debug

# Write to a one-off location
python collector.py --output ~/Desktop/today.json

# Collect and refresh the CSV view in one run
python collector.py --export-csv

# Refresh today's connections leaderboards (re-run later in the day as more
# connections play, without re-collecting scores)
python collector.py --sync-leaderboards

# Export an already-collected store to CSV
python export_csv.py --input ~/Desktop/today.json --output ~/Desktop/today.csv
```

## Troubleshooting

If LinkedIn redirects to the login page during a normal run, your saved
session has expired. Re-run:

```
python setup_auth.py
```

If the script raises an `AuthStoreError` about being unable to decrypt
`linkedin_state.enc`, the Fernet master key in the OS credential store has
been removed or replaced (for example after restoring a profile from backup,
or after running on a different machine). Run `python setup_auth.py --delete`
to remove the stale file (see "Deleting or rotating your saved session" below),
then re-run `setup_auth.py` to regenerate it.

On headless Linux / WSL / Docker / CI, no keyring backend is typically
available. Generate a Fernet key once and export it before running the
script:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export LINKEDIN_GAMES_MASTER_KEY=<paste-key-here>
```

The same key must be reused across runs. If `$LINKEDIN_GAMES_MASTER_KEY` is
unset and no keyring is available, the script falls back to an interactive
passphrase prompt with PBKDF2; that mode is not suitable for unattended runs.

### Deleting or rotating your saved session

```
python setup_auth.py --delete       # delete the saved session (keeps the Fernet key)
python setup_auth.py --delete-key   # full local wipe: session + Fernet key + salt
```

- `--delete` removes the encrypted `linkedin_state.enc` only. The Fernet master
  key stays in your OS credential store, so re-running `setup_auth.py` reuses it.
- `--delete-key` additionally removes the Fernet key (keyring entry) and the
  `passphrase.salt`, for a full local wipe — e.g. when retiring a machine. It
  cannot unset `$LINKEDIN_GAMES_MASTER_KEY`; if you use that env var, unset it
  separately.

**To rotate the Fernet key**, wipe and re-authenticate — the new login is
encrypted under a freshly generated key:

```
python setup_auth.py --delete-key
python setup_auth.py
```

> **IMPORTANT NOTE: deleting locally does NOT invalidate the token.**
> The saved session contains your LinkedIn `li_at` cookie, a **bearer token**
> that LinkedIn's servers honor regardless of whether your local copy still
> exists. If the token may have been **compromised or copied**, deleting the
> `.enc` (or the key) only removes _your_ copy — an attacker's copy keeps working
> until the session is revoked **server-side**. Revoke it on LinkedIn **first**:
> **Settings & Privacy → Sign in & security → "Where you're signed in"** → sign
> out the device, **or change your password** (which ends active sessions). Only
> after revoking should you `--delete` locally and re-authenticate.

## Syncing a CSV output file to Google Sheets

The easiest way to sync the data from the collector to Google Sheets is to use
its built-in `=IMPORTDATA` command to download the CSV file from an Internet
accessible location. One way to do this is to save the CSV file to a local folder
on your machine which syncs to a Google Drive. Once you have located the file in
Google Drive, open its sharing settings, set its permissions to "Anyone with the
link can view," then copy the link. You will get a link in this format:

```
https://drive.google.com/file/d/<documentID>/view?usp=sharing
```

This link will include a document ID, but Google Sheets is expecting a link in
a slightly different format. Take the `documentID` value from the first URL, and
paste it into the following URL:

```
https://drive.google.com/uc?export=download&id=<documentID>
```

To test this, open the URL. If this results in the file being downloaded, it is set up
correctly. From there, you can go into a Google Sheet, and in cell A1, add the following formula:

```
=IMPORTDATA("https://drive.google.com/uc?export=download&id=<documentID>")
```

Assuming the permissions are set up correctly, your data should appear in the spreadsheet,
and whenever the CSV file gets updated the changes will automatically propagate to the Google
Spreadsheet (keep in mind there may be some amount of lag between when the file gets
updated and when the sheet picks up the update.)

**A couple of items to note about importing to Google Sheets:**

- Google Sheets does not seem to handle M:SS values properly, so I generally
  have to format time values in H:MM format to get the values to look correct.  
  Generally this should work fine, but if a puzzle takes ever an hour or more
  to solve this will result in inaccurate values being displayed. If you can
  find a better way to handle the number formatting for these values, let me
  know. Then again, if a puzzle ever takes an hour to finish you're likely
  not having a great day and you should probably just call in sick.

- If you make changes to your games layout which might impact the way items
  on the sheet are displayed, the cleanest way to "reset" the sheet is to
  temporarily delete the `=IMPORTDATA` statement from cell A1, then add it
  back to refresh all the data. Note that any existing formatting will
  remain in place, so additional tweaking may be needed to get things back in order.

# Limitations and Known Issues

## The "Anchor Game", explained

The "anchor game" specified in the configuration should ideally be the one you play
first each day, or at least one you can be certain will be played by the time the
script runs (which in my case happens to be Zip.) I have found that currently,
the only reliable way to determine the played/unplayed status of all of the games is to
open the results page for a game which has already been completed for the day.

This is important because an attempt to open the results page for an unplayed game
will automatically redirect to the game page, which may cause the game timer to
start running. The script is designed to detect the redirect and fail out with an error
if the anchor game is detected to be unplayed, but this can still affect the timer.

Pinpoint is currently the only game on LinkedIn that does not use a timer,
and can be used as a timer-safe option for the anchor if you play it regularly.

_Why not read state from the games hub instead?_
It does appear that https://www.linkedin.com/games/ shows different icons
depending on each game's played/unplayed status, but through testing I have
determined that the only differences between the two statuses are static icon
assets, which are brittle and likely not a reliable indicator for this purpose.

## Adding a new game

The master list of games is located in config.py, If a new game is added to LinkedIn,
it would need to be added there first, then added to the list of games config.json
in order to be tracked. A sample is provided below:

```python
     {
        "key":     "wend", # This should match the game's name string in the URL
        "name":    "Wend", # The display name for the game
        "url":     "https://www.linkedin.com/games/wend/results/",
        "is_time": True, # This will be false for non-timer based games like Pinpoint
    },
```

## Time Zones

LinkedIn is based in the US Pacific Time Zone (PST/PDT), and the daily changeover of games happens at Midnight in that time zone. The script
accounts for this with a built-in time zone offset that collects results based on the current day in PST/PDT, but the `--timezone` parameter can be used
to override the local time zone if there is a need for it. This won't affect the actual collection of results (which will always be tied to US Pacific Time),
but if you run the script after Midnight in your local time zone but before Midnight PST/PDT it will warn you that results are still being
recorded for the previous day.

## Daily Averages

The average solve time for each puzzle is a moving target, and will almost inevitably trend higher over the course of any given day.  
This means that results collected early in the day will frequently have lower average times than results later in the day, often by
as much as 20 seconds. Keep this in mind when setting up automated jobs to collect results, and remember that the `--update` parameter
can be used to update averages even if you have collected the results earlier in the day.
