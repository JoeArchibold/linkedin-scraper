# Setup

This is the local-storage build of the LinkedIn Games score collector. The
script logs into LinkedIn once interactively, then runs headless to collect
daily game scores into a local JSON store. No Google account required. A
spreadsheet-friendly CSV can be exported from the store on demand with
`export_csv.py` (see "Exporting to CSV" below).

The only persistent secret is your LinkedIn session state, which is encrypted
at rest. See "Local Auth State" below.

## Installation Location

You can clone or copy this project anywhere on disk and run the script from
any working directory. The commands below assume you are inside the project's
`scripts/` folder; adjust paths as needed.

**To use this project as a Claude Code skill**, the project root must be
placed at `~/.claude/skills/Linkedin-games/` (so the script lives at
`~/.claude/skills/Linkedin-games/scripts/`). On Windows, `~` expands to
`%USERPROFILE%` (typically `C:\Users\<you>\.claude\skills\Linkedin-games\`).
For ad-hoc / non-skill use, any location works.

## Python Dependencies

Python 3.10 or newer is required. Using a virtual environment is recommended.

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

After this, `main.py` runs fully headless.

## Local Auth State

The collector creates or uses these local values:

| Location | Purpose |
|----------|---------|
| `scripts/.env` | Optional. Currently only used to set `RESULTS_JSON`. Create from `scripts/.env.example`. |
| `scripts/sheet_layout.json` | Column layout. Controls which games are collected, in what order, and whether to log puzzle numbers and the day of week. |
| `<user data dir>/linkedin_state.enc` | Fernet-encrypted Playwright storage state for LinkedIn. |
| `<user data dir>/passphrase.salt` | Created only if the passphrase fallback is used. |
| OS credential store: `linkedin-games-data-collector` / `fernet-master-key` | 44-byte Fernet key that decrypts the `.enc` file. |

`<user data dir>` resolves per OS via `platformdirs`:

| OS | Path |
|----|------|
| Windows | `%LOCALAPPDATA%\linkedin-games\` (e.g. `C:\Users\<you>\AppData\Local\linkedin-games\`) |
| macOS | `~/Library/Application Support/linkedin-games/` |
| Linux | `$XDG_DATA_HOME/linkedin-games/` (defaults to `~/.local/share/linkedin-games/`) |

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

By default `main.py` writes a JSON store, `results.json`, to whatever directory
you ran it from. To pin a fixed location, set `RESULTS_JSON` in `scripts/.env`:

```text
# Windows
RESULTS_JSON=C:\Users\<you>\Documents\linkedin-games\results.json

# macOS / Linux
RESULTS_JSON=/Users/<you>/Documents/linkedin-games/results.json
```

Relative paths resolve against the current working directory. The CLI flag
`--output FILE` overrides both `.env` and the default for one-off runs.

> **Note:** `main.py` writes JSON only. The older `RESULTS_CSV` setting and
> direct-to-CSV writing have been removed; produce a CSV from the JSON store
> with `export_csv.py` (see "Exporting to CSV").

### JSON store format

The store is a single JSON object keyed by ISO date (`YYYY-MM-DD`). Each day
holds the day of week and a `games` object keyed by game id:

```jsonc
{
  "2026-06-10": {
    "day_of_week": "Wednesday",
    "games": {
      "zip":  { "number": "450", "score": "0:28", "avg": "0:24" },
      "wend": { "number": "2",   "score": "0:32", "avg": "1:01" }
    }
  }
}
```

Because games are keyed by id rather than by fixed columns, adding or removing a
game needs no migration — new ids simply appear in future entries, and games no
longer in the layout are preserved untouched. Writes are atomic (a temp file is
swapped into place), so an interrupted run cannot corrupt the store.

## Customising Which Games Are Collected

Edit `scripts/sheet_layout.json`:

```jsonc
{
  "include_day_of_week": true,       // include/ exclude the Day of Week column
  "include_puzzle_numbers": false,   // include/exclude a "<Game> #" column per game
  "anchor_game": "zip",              // the game you typically play first;
                                     // its results page is loaded first when
                                     // nothing is recorded yet today, since
                                     // it's the most likely to be complete.
                                     // Omit/null for current behavior (the
                                     // first game in 'games' is used).
  "games": [                         // order = exported CSV column order; these
    "zip",                           // can be reordered to your preferences
    "tango",                         // or you can omit one or more games to exclude them
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
in `games`; otherwise startup fails with a clear error.

The layout controls the **exported CSV** (see "Exporting to CSV"); the JSON
store itself is keyed by game id and is unaffected by column order. Exported CSV
column order is always:

```
Date, [Day of Week,] <game columns in JSON order>
```

Per game, columns are `[<Game> #,] <Game> Time-or-Guesses, <Game> Avg`.

You can change the layout at any time after results have been collected — the
JSON store needs no migration, since it stores games by id rather than by fixed
columns. The next `export_csv.py` run simply regenerates the CSV against the new
layout.

## First Run Check
After setting up authentication, the following command can be used to verify that the script is functioning correctly

```
python main.py --dry-run --summary-only
```

This authenticates, fetches today's scores, prints the result table, and
exits without writing the store. Confirm scores look right, then run for real:

```
python main.py
```

## Exporting to CSV

`main.py` writes the JSON store only. To produce a spreadsheet-friendly CSV from
it, use `export_csv.py`:

```
# Default: read the configured JSON store, write a CSV beside it
python export_csv.py

# Explicit input/output
python export_csv.py --input results.json --output scores.csv
```

Behavior and notes:

- The default input is `$RESULTS_JSON` (else `./results.json`); the default
  output is the input path with a `.csv` extension.
- Columns and their order come from `scripts/sheet_layout.json`, so the CSV
  always reflects the current layout. The file is **regenerated in full** on
  each run — it is never edited in place — which avoids header drift and
  column-misalignment problems.
- The JSON store remains the source of truth; the CSV is a disposable view you
  can recreate at any time. Games present in the store but absent from the
  layout are simply omitted from the CSV (and left intact in the store).
- It is dependency-free (Python standard library only); no pandas required.

| Flag | Behavior |
|------|----------|
| `--input <FILE>` | JSON store to read. Defaults to `$RESULTS_JSON`, else `./results.json`. |
| `--output <FILE>` | CSV to write. Defaults to the input path with a `.csv` suffix. |

## Command-Line Parameters

`main.py` accepts the following flags. They can be combined freely (e.g.
`--update --dry-run` for a full fetch + preview with no write).

| Flag | Behavior |
|------|----------|
| *(none)* | **Smart mode.** Reads the JSON store, looks for today's entry, and fetches only the games that are missing. If today's entry is complete, exits without touching the network. If no entry exists, fetches every configured game and adds a new one. |
| `--update` | Fetch every configured game and refresh both score and average values regardless of what's already stored. Use this when LinkedIn has corrected a score or when you want to force averages to recompute. |
| `--dry-run` | Run the full fetch + check logic and print the results table, but do not write or modify the store. Useful for verifying a setup change before committing it to the file. |
| `--debug` | Save a PNG screenshot and an HTML dump for every page Playwright visits, under `scripts/debug/<timestamp>/`. Use when scores come back wrong or missing to inspect what LinkedIn actually returned. Output is **not** auto-pruned. |
| `--show-status` | Add a Status column to the printed results table indicating, per game, whether the score was newly fetched, already present, skipped, or errored. Does not affect stored contents. |
| `--summary-only` | Suppress informational log lines and print only the results table plus errors. Recommended when invoking from a Claude skill or any other context where compact output matters. |
| `--timezone <TZ>` | Override local-timezone auto-detection used for the "are you running near midnight Pacific?" warning. Accepts any IANA timezone name, e.g. `America/New_York`, `Europe/London`, `Asia/Tokyo`. Does **not** change the LinkedIn/Pacific date used for the stored entry. |
| `--output <FILE>` | Override the JSON store path for this run. Precedence: `--output` > `$RESULTS_JSON` in `scripts/.env` > `./results.json` in the current working directory. Relative paths resolve against the CWD. |

### Common invocations

```bash
# Normal daily run — smart mode, full logs
python main.py

# Compact output (recommended for skill / automation use)
python main.py --summary-only

# Re-fetch everything (e.g. after LinkedIn corrected a score)
python main.py --update

# Preview a config change without writing
python main.py --dry-run --show-status

# Diagnose a missing or wrong score
python main.py --debug

# Write to a one-off location
python main.py --output ~/Desktop/today.json

# Export the collected store to CSV
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
or after running on a different machine). Delete the file from the user data
directory and re-run `setup_auth.py` to regenerate it.

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

## Limitations / Known Issues

**Anchor Games**
Currently, the script needs to open the results page for a game which has been completed
in order to determine which games have and have not been played yet for the day.  The script 
defaults to using Zip for this (the value is configurable in the `sheet_layout.json` file), 
because that is the game I generally play first, and I can typically guarantee that it
will be played by the time the script runs.  
  
Be aware that if the script runs before that game is played,
it can leave the timer running in the unplayed game and affect your solve times.  If I can determine a way
to get played/unplayed states of the games without opening a results page I will implement it, but so far
I have not been able to find another reliable way to get this information (`https:\\linkedin.com\games` shows 
static icons with different played/unplayed states, but does not provide any usable DOM elements to determine the state from,
and asset file URLs are likely to be too brittle to be a reliable indicator.)  Pinpoint has no timer, and can be used as a check that
will not affect solve times, but tends to be less played than the other games, so it may be less reliable.

**Adding or reordering games**
The JSON store is keyed by game id, so reordering games in `sheet_layout.json`,
or removing one, takes effect immediately with no migration — existing entries
are left untouched and the exported CSV simply regenerates in the new order.
Adding a brand-new LinkedIn game still requires a small code change: add an entry
to `GAMES` in `config.py` (id, display name, results URL, and whether it is
timed) and include its id in `sheet_layout.json`. Note that on a new game's first
day LinkedIn may not report a daily average yet, so the average can be briefly
blank.

**Notes on Time Zones**
LinkedIn is based in the US Pacific Time Zone (PST/PDT), and the daily changeover of games happens at Midnight in that time zone.  The script
accounts for this with a built-in time zone offset that collects results based on the current day in PST/PDT, but the --timezone parameter can be used
to override this if desired.  

**Daily Averages**
The average solve time for each puzzle is a moving target, and will almost inevitably trend higher over the course of any given day.  
This means that results collected early in the day will frequently have lower average times than results later in the day, often by
as much as 20 seconds.  Keep this in mind when setting up automated jobs to collect results, and remember that the `--update` parameter
can be used to update averages even if you have collected the results earlier in the day.

