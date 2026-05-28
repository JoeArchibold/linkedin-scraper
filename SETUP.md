# Setup

This is the CSV-only build of the LinkedIn Games score collector. The script
logs into LinkedIn once interactively, then runs headless to collect daily
game scores into a local CSV file. No Google account required.

The only persistent secret is your LinkedIn session state, which is encrypted
at rest. See "Local Auth State" below.

## Python Dependencies

Install the script dependencies from the `scripts` folder:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
pip install -r requirements.txt
playwright install chromium
```

The second command downloads the Chromium browser binary that Playwright
controls. It is required.

## One-Time LinkedIn Login

Run the setup script and log in to LinkedIn in the browser window it opens:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
python setup_auth.py
```

A visible Chromium window appears at LinkedIn's login page. Log in normally.
Once your feed or home page has loaded, return to the terminal and press
Enter. The script encrypts your session state (cookies + localStorage) with
Fernet and writes it to the per-OS data directory described below.

After this, `main.py` runs fully headless.

## Local Auth State

The collector creates or uses these local values:

| Location | Purpose |
|----------|---------|
| `scripts/.env` | Optional. Currently only used to set `RESULTS_CSV`. Create from `scripts/.env.example`. |
| `scripts/sheet_layout.json` | Column layout. Controls which games are collected, in what order, and whether to log puzzle numbers and the day of week. |
| `<user data dir>/linkedin_state.enc` | Fernet-encrypted Playwright storage state for LinkedIn. |
| `<user data dir>/passphrase.salt` | Created only if the passphrase fallback is used. |
| OS credential store: `linkedin-games-data-collector` / `fernet-master-key` | 44-byte Fernet key that decrypts the `.enc` file. |

`<user data dir>` resolves per OS via `platformdirs`:

| OS | Path |
|----|------|
| Windows | `%LOCALAPPDATA%\linkedin-games\` (e.g. `C:\Users\Brian\AppData\Local\linkedin-games\`) |
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

By default `main.py` writes `results.csv` to whatever directory you ran it
from. To pin a fixed location, set `RESULTS_CSV` in `scripts/.env`:

```text
RESULTS_CSV=C:\Users\Brian\Documents\linkedin-games\results.csv
```

Relative paths resolve against the current working directory. The CLI flag
`--output FILE` overrides both `.env` and the default for one-off runs.

## Customising Which Games Are Collected

Edit `scripts/sheet_layout.json`:

```jsonc
{
  "include_day_of_week": true,       // false to drop the Day of Week column
  "include_puzzle_numbers": false,   // true to add a "<Game> #" column per game
  "games": [                         // order = CSV column order; omit a game to exclude it
    "zip",
    "tango",
    "queens",
    "patches",
    "mini_sudoku",
    "crossclimb",
    "pinpoint"
  ]
}
```

Valid game keys: `zip`, `tango`, `queens`, `patches`, `mini_sudoku`,
`crossclimb`, `pinpoint`.

CSV column order is always:

```
Date, [Day of Week,] <game columns in JSON order>
```

Per game, columns are `[<Game> #,] <Game> Time-or-Guesses, <Game> Avg`.

If you change the layout after results have been collected, you have two
options:

1. Delete the existing CSV (or set `RESULTS_CSV` to a new path). A fresh
   header row is written on first run with the new layout.
2. Edit the existing CSV's header row by hand to match the new layout.
   The writer matches columns by header name (case- and punctuation-
   insensitive), so any subset of the layout that already exists in the
   header keeps working.

## First Run Check

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
python main.py --dry-run --summary-only
```

This authenticates, fetches today's scores, prints the result table, and
exits without writing the CSV. Confirm scores look right, then run for real:

```powershell
python main.py --summary-only
```

## Troubleshooting

If LinkedIn redirects to the login page during a normal run, your saved
session has expired. Re-run:

```powershell
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
