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
| `scripts/.env` | Optional and **deprecated**. Can set `RESULTS_JSON` / `RESULTS_CSV` output paths. Prefer `output_path` in `config.json` instead (see "Output Location"). Create from `scripts/.env.example` if you still need it. |
| `scripts/config.json` | Column layout and output paths. Controls which games are collected, in what order, whether to log puzzle numbers and the day of week, and (optionally) where the JSON store and exported CSV are written. |
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

**Set an explicit `output_path` in `scripts/config.json`.** This is the single
most important thing to configure: it pins where your data lives so it never
depends on which directory a run happens to start in (which matters a lot for
scheduled jobs). Outputs are a directory (`output_path`) plus two filenames:

```jsonc
{
  "output_path": "C:/Users/<you>/Documents/linkedin-games",
  "output_json": "results.json",   // optional, default results.json
  "output_csv":  "results.csv",    // optional, default results.csv
  "games": [ /* ... */ ]
}
```

- `output_path` is the directory the JSON store and exported CSV are written to.
  **An absolute path (or one starting with `~`) is strongly recommended.** A
  *relative* `output_path` resolves against the current working directory, and
  if you omit it entirely the directory defaults to that CWD — fine for ad-hoc
  runs, risky for scheduled ones, which is why an explicit path is preferred.
- `output_json` / `output_csv` are **bare filenames** within `output_path` (no
  directory part — a value containing a path separator is rejected). They
  default to `results.json` / `results.csv`.

The full resolution order for each path is:

| | JSON store | CSV view |
|---|---|---|
| 1. CLI flag | `--output` (full path) | `--csv-output` (full path) |
| 2. Config file | `output_path` + `output_json` | `output_path` + `output_csv` |
| 3. `.env` *(deprecated)* | `RESULTS_JSON` | `RESULTS_CSV` |
| 4. Built-in default | `./results.json` (CWD) | JSON path with a `.csv` suffix |

> **Deprecated:** `scripts/.env` (`RESULTS_JSON` / `RESULTS_CSV`) still works as a
> lower-precedence fallback, but is deprecated in favour of `output_path` in the
> config file. New setups should not need `.env` at all.
>
> Both `.env` paths and a relative `output_path` resolve against the **current
> working directory**; prefer an absolute `output_path` so the location is fixed.

> **Note:** `main.py` writes the JSON store directly; CSV is always a derived
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

Edit `scripts/config.json`:

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
  "output_path": "~/linkedin-games", // directory the outputs are written to.
                                     // Absolute or ~ recommended. A relative
                                     // value resolves against the directory you
                                     // run from; omit to default to that CWD.
  "output_json": "results.json",     // JSON store filename within output_path
                                     // (bare filename). Default results.json.
  "output_csv": "results.csv",       // exported-CSV filename within output_path
                                     // (bare filename). Default results.csv.
  "export_csv_on_run": false,        // optional: when true, regenerate the CSV
                                     // automatically after every collection run,
                                     // as if --export-csv were always passed.
                                     // Default false. (No effect on --dry-run or
                                     // when no new scores were written.)
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
in `games`; otherwise startup fails with a clear error. A game listed more than
once in `games` is collected only once — the duplicate is ignored and a warning
is logged so you can remove it.

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

CSV is always a derived view of the JSON store. You can produce it three ways:

```
# As part of a collection run — collect, then regenerate the CSV
python main.py --export-csv

# Standalone, from an already-collected store
python export_csv.py

# Standalone with explicit input/output
python export_csv.py --input results.json --output scores.csv
```

To regenerate the CSV on **every** run without passing `--export-csv`, set
`"export_csv_on_run": true` in `config.json`. It behaves exactly as if
`--export-csv` were always passed: the CSV is rewritten after each run that
writes new scores (and skipped on `--dry-run` or when nothing new was
collected). The destination follows the same precedence as below.

Behavior and notes:

- Both `main.py --export-csv` and `export_csv.py` resolve the CSV destination
  the same way: `--csv-output`/`--output` flag, then the config's
  `output_path`/`output_csv`, then `$RESULTS_CSV` *(deprecated)*, then the JSON
  path with a `.csv` suffix. The JSON store path that `export_csv.py` reads
  follows the same precedence as `main.py` (see "Output Location").
- Columns and their order come from `scripts/config.json`, so the CSV
  always reflects the current layout. The file is **regenerated in full** on
  each run — it is never edited in place — which avoids header drift and
  column-misalignment problems.
- The JSON store remains the source of truth; the CSV is a disposable view you
  can recreate at any time. Games present in the store but absent from the
  layout are simply omitted from the CSV (and left intact in the store).
- It is dependency-free (Python standard library only); no pandas required.

| Flag | Behavior |
|------|----------|
| `--input <FILE>` | JSON store to read. Defaults to the config's `output_path`/`output_json`, then `$RESULTS_JSON`, then `./results.json`. |
| `--output <FILE>` | CSV to write. Defaults to the config's `output_path`/`output_csv`, then `$RESULTS_CSV`, then the input path with a `.csv` suffix. |

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
| `--output <FILE>` | Override the JSON store path for this run. Precedence: `--output` > `output_path`/`output_json` in `config.json` > `$RESULTS_JSON` *(deprecated)* > `./results.json`. A relative `--output` resolves against the CWD. |
| `--export-csv` | After writing the JSON store, also regenerate the CSV view. Destination precedence: `--csv-output` > `output_path`/`output_csv` in `config.json` > `$RESULTS_CSV` *(deprecated)* > the JSON path with a `.csv` suffix. A CSV failure is reported but does not undo the JSON write. |
| `--csv-output <FILE>` | Path for the exported CSV. Implies `--export-csv`. Overrides the config's `output_path`/`output_csv` and `$RESULTS_CSV` for this run. |

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

# Collect and refresh the CSV view in one run
python main.py --export-csv

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
To learn which games have and haven't been played yet today, the script opens the
results page of a single **anchor** game and reads its "Play another game" list.
That list only renders on a *completed* results page, so the anchor needs to be a
game that has already been played by the time the script runs. The anchor defaults
to Zip and is configurable via `anchor_game` in `config.json` — set it to
whichever game you reliably play first.

*Why opening a results page matters:* navigating to an unplayed **timed** game's
results URL redirects to the playable game and can leave its timer running,
inflating your solve time. The anchor mechanism exists precisely so the script can
identify the unplayed games and then **skip** them instead of opening each one.

*Timer-safety guard (when the anchor itself hasn't been played).* If the anchor's
own results page redirects — i.e. you haven't played the anchor yet — the script
**stops without probing any other game**, reports every game as not-yet-played, and
exits without writing (exit code 0). This keeps a too-early run from opening, and
potentially starting timers on, your other unplayed games. You'll see a warning
like:

```
Anchor game (Zip) has not been played yet today — skipping all game probes to
avoid starting timers on unplayed games. Nothing collected this run; re-run after
playing the anchor.
```

Just re-run after you've played the anchor and collection proceeds normally.
Three practical consequences for **scheduled jobs**:

- **Set an explicit, absolute `output_path`** (see "Output Location"). A scheduled
  job's working directory is often not where you think, so relying on the CWD
  default can scatter `results.json` in unexpected places. Pinning `output_path`
  matters most for unattended runs.
- Pick an anchor you're confident is played before the job runs. If the anchor
  isn't played, that run collects nothing (by design) — a later run catches up.
- The guard still loads the anchor's *own* page (that one navigation is
  unavoidable), so a timed anchor is itself slightly exposed. Setting
  `anchor_game` to **`pinpoint`** removes even that risk — Pinpoint has no timer,
  so loading it when unplayed is harmless. The trade-off is that Pinpoint tends to
  be played less reliably, so a Pinpoint anchor is best paired with running the
  job after you know it's done.

*Why not read state from the games hub instead?* `https://www.linkedin.com/games/`
does show a played/unplayed checkmark per game, but investigation confirmed it is
baked into the game's static art image with **no** accompanying DOM class,
attribute, or text — the played and unplayed images are just different assets
(content-hashed URLs). That signal is opaque (nothing says which image means
"unplayed") and silently brittle (the hash changes whenever LinkedIn rebuilds the
asset), so the results-page method above remains the reliable approach.

**Adding or reordering games**
The JSON store is keyed by game id, so reordering games in `config.json`,
or removing one, takes effect immediately with no migration — existing entries
are left untouched and the exported CSV simply regenerates in the new order.
Adding a brand-new LinkedIn game still requires a small code change: add an entry
to `GAMES` in `config.py` (id, display name, results URL, and whether it is
timed) and include its id in `config.json`. Note that on a new game's first
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

