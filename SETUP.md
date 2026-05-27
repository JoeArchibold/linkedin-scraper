# Setup

This project needs two kinds of local authentication before `scripts/main.py`
can run headlessly:

1. A saved LinkedIn browser session for Playwright.
2. A Google OAuth client and user token for writing to Google Sheets.

LinkedIn session state and the Google OAuth user token are encrypted with
[Fernet](https://cryptography.io/en/latest/fernet/) (AES-128-CBC + HMAC-SHA256)
and written to the user's per-OS data directory. Only the 44-byte Fernet master
key lives in the OS credential store (Windows Credential Manager / macOS
Keychain / Linux Secret Service) via Python's `keyring` package.

The master key is resolved in this order on every run:

1. `$LINKEDIN_GAMES_MASTER_KEY` environment variable, if set.
2. The OS credential store entry (created automatically on first run).
3. An interactive passphrase prompt with PBKDF2-HMAC-SHA256 (fallback for
   headless environments with no keyring backend; salt is stored beside the
   ciphertext).

The Google OAuth client JSON downloaded from Google Cloud Console remains a
local bootstrap file.

The setup script is:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
python setup_auth.py
```

## Local Auth State

The auth setup creates or uses these local values:

| Location | Purpose |
|----------|---------|
| `scripts/.env` | Spreadsheet ID and worksheet tab name. Create this from `scripts/.env.example`. |
| `scripts/sheet_layout.json` | Column layout, game inclusion/exclusion order, and whether to log puzzle numbers. Drives both `create_sheet.py` and the daily writer. |
| `scripts/auth/google_credentials.json` | OAuth client configuration downloaded from Google Cloud Console. |
| `<user data dir>/linkedin_state.enc` | Fernet-encrypted Playwright storage state for LinkedIn (cookies, localStorage). |
| `<user data dir>/google_token.enc` | Fernet-encrypted cached Google user OAuth token. |
| `<user data dir>/passphrase.salt` | Created only if the passphrase fallback is used. |
| OS credential store: `linkedin-games-data-collector` / `fernet-master-key` | 44-byte Fernet key that decrypts the `.enc` files. |

`<user data dir>` resolves per OS via `platformdirs`:

| OS | Path |
|----|------|
| Windows | `%LOCALAPPDATA%\linkedin-games\` (e.g. `C:\Users\Brian\AppData\Local\linkedin-games\`) |
| macOS | `~/Library/Application Support/linkedin-games/` |
| Linux | `$XDG_DATA_HOME/linkedin-games/` (defaults to `~/.local/share/linkedin-games/`) |

On POSIX systems the `.enc` files are written with mode `0600`. On Windows they
live under `%LOCALAPPDATA%`, which is already ACL-protected for the current
user.

The local files under `scripts/auth/` are intentionally ignored by Git. If
plaintext `linkedin_state.json` or `google_token.json` files from an older
version of the skill are present under `scripts/auth/`, they are migrated into
the encrypted store automatically on first run and can then be deleted.

## Python Dependencies

Install the script dependencies from the `scripts` folder:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
pip install -r requirements.txt
playwright install chromium
```

## Environment File

Create `scripts/.env` from the example:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
copy .env.example .env
```

Edit `.env`:

```text
SPREADSHEET_ID=your_spreadsheet_id_here
WORKSHEET_NAME=Sheet1
```

The spreadsheet ID is the value in the Google Sheets URL between
`/spreadsheets/d/` and `/edit`.

## Google Cloud OAuth Setup

The Google Sheets connection uses OAuth as an installed desktop app. The script
does not use a service account.

High-level flow:

1. Create or select a Google Cloud project.
2. Enable the Google Sheets API for that project.
3. Configure the OAuth consent screen.
4. Create an OAuth 2.0 Client ID with application type `Desktop app`.
5. Download the client JSON file.
6. Save it as `scripts/auth/google_credentials.json`.
7. Run `python setup_auth.py` and complete the browser consent flow.

Important testing-mode behavior: for an OAuth consent screen configured as
External with publishing status `Testing`, Google issues refresh tokens that
expire after 7 days for non-profile scopes such as Google Sheets. In this
project, that means the stored `google_token` keyring entry may stop working
weekly. The downloaded OAuth client file, `google_credentials.json`, does not
usually need to be recreated; re-run `python setup_auth.py` to complete consent
again and replace the keyring token. Moving the app to production avoids the
7-day testing-token expiration, subject to Google's app verification
requirements for the scopes used.

Detailed steps:

1. Open the Google Cloud Console:
   <https://console.cloud.google.com/>
2. Select an existing project or create a new one.
3. Go to `APIs & Services` > `Library`.
4. Search for `Google Sheets API`, open it, and click `Enable`.
5. Go to `APIs & Services` > `OAuth consent screen` or `Google Auth Platform`.
6. Configure the app for external or internal use, depending on the account type available in your Google Workspace setup.
7. Fill in the required app information. For personal/local use, the app can stay in testing mode.
8. Add yourself as a test user if the app is external and still in testing mode.
9. Go to `APIs & Services` > `Credentials`.
10. Click `Create Credentials` > `OAuth client ID`.
11. Choose `Desktop app` as the application type.
12. Create the client and download the JSON file.
13. Rename the downloaded file to `google_credentials.json`.
14. Put it here:

```text
C:\Users\Brian\.claude\skills\Linkedin-games\scripts\auth\google_credentials.json
```

Google's official references:

- Google Sheets API Python quickstart: <https://developers.google.com/workspace/sheets/api/quickstart/python>
- Create Google Workspace credentials: <https://developers.google.com/workspace/guides/create-credentials>
- Enable Google Workspace APIs: <https://developers.google.com/workspace/guides/enable-apis>
- Google OAuth refresh token expiration: <https://developers.google.com/identity/protocols/oauth2#expiration>

## What `setup_auth.py` Does

`setup_auth.py` runs two setup steps.

### Step 1: LinkedIn Authentication

The script opens a visible Chromium browser at LinkedIn's login page. You log in
manually. After your LinkedIn feed or home page loads, return to the terminal
and press Enter.

The script then encrypts Playwright's browser storage state and writes it to:

```text
<user data dir>/linkedin_state.enc
```

That file contains LinkedIn cookies and localStorage, sealed with the Fernet
master key in the OS credential store. Treat the combination of file plus key
like a password: any process running as your local user can decrypt it through
the same APIs until LinkedIn expires or invalidates the session.

### Step 2: Google Sheets Authentication

The script checks for:

```text
scripts/auth/google_credentials.json
```

If that file exists, it starts the Google OAuth browser flow. Sign in with the
Google account that has access to the target spreadsheet and approve the Sheets
permission.

After consent succeeds, the script writes:

```text
<user data dir>/google_token.enc
```

That encrypted token is reused on later runs. If it expires and has a refresh
token, the script refreshes it automatically and saves the refreshed token back
to the same encrypted file. If it cannot be refreshed, run
`python setup_auth.py` again.

## Creating a New Spreadsheet

`scripts/create_sheet.py` provisions a fresh workbook (or adds a worksheet to
an existing one) using `scripts/sheet_layout.json` as the source of truth for
column order, game inclusion, and headers.

### Step-by-Step

1. **Confirm prerequisites.** `python setup_auth.py` must have been run at
   least once so the Google OAuth flow has a cached user token. Verify
   `scripts/auth/google_credentials.json` exists. If neither is in place,
   complete the rest of this document first.

2. **(Optional) Edit `scripts/sheet_layout.json`** to choose the spreadsheet
   title, worksheet tab name, which games to include and in what order, and
   whether to log puzzle numbers. See the schema reference below for valid
   keys. Skip this step to use the defaults (mirrors the current sheet
   structure).

3. **Run the creation script:**

   ```powershell
   cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
   python create_sheet.py
   ```

   To add the layout as a new tab on an existing workbook instead of creating
   a brand-new file:

   ```powershell
   python create_sheet.py --existing-id <spreadsheet-id> --worksheet "2027 Scores"
   ```

   To try a layout file other than the default:

   ```powershell
   python create_sheet.py --layout path\to\custom_layout.json
   ```

4. **Approve the additional Google consent prompt (first run only).** The
   script needs the `drive.file` OAuth scope to create new spreadsheets,
   which the daily-run setup didn't request. A browser window opens; sign in
   with the same Google account you used during `setup_auth.py` and approve.
   The encrypted token in the user data directory is then upgraded with the
   new scope, and subsequent runs of `create_sheet.py` and `main.py` are
   silent.

5. **Copy the printed spreadsheet ID.** The script ends by printing
   something like:

   ```text
   Spreadsheet URL : https://docs.google.com/spreadsheets/d/1AbCDeFGhIjK.../edit
   Spreadsheet ID  : 1AbCDeFGhIjK...
   Worksheet       : Sheet1
   ```

6. **Update `scripts/.env`** to point `main.py` at the new sheet:

   ```text
   SPREADSHEET_ID=1AbCDeFGhIjK...
   WORKSHEET_NAME=Sheet1
   ```

   Use the worksheet name printed by the script. Skip this step if you used
   `--existing-id` against the spreadsheet that `.env` already points at and
   you simply want to keep writing to a different tab — in that case update
   only `WORKSHEET_NAME`.

7. **Share the spreadsheet (optional).** A workbook created through
   `drive.file` is only accessible to the signing-in Google account.
   Open the printed URL in a browser and use Sheets's Share dialog to grant
   access to other accounts. The script never modifies sharing permissions.

8. **Verify with a dry run:**

   ```powershell
   python main.py --dry-run --summary-only
   ```

   This authenticates against the new spreadsheet, reads its headers (no row
   exists for today yet), and prints the result table without writing.

9. **Populate it:**

   ```powershell
   python main.py --summary-only
   ```

   The daily writer reads row 1 of the new sheet, matches the headers against
   the layout, and writes today's row. From here on, the new spreadsheet is
   the live target.

> [!NOTE]
> `create_sheet.py` creates an **empty** workbook with headers and formatting
> only. Historical rows are not migrated from the previous sheet. If you want
> the data carried over, copy/paste the prior rows into the new sheet
> manually after step 5 — column positions match by header, so paste order
> doesn't matter as long as the source columns line up.

### `sheet_layout.json` schema

```jsonc
{
  "title": "LinkedIn Games Tracking",    // used only when creating a new workbook
  "worksheet_name": "Sheet1",            // tab name inside the workbook
  "include_puzzle_numbers": false,       // true => add a "<Game> #" column per game
  "index_prefix": ["date"],              // appears before the game columns
  "games": [                             // order = column order; omit a game to exclude it
    "zip", "tango", "queens", "patches",
    "mini_sudoku", "crossclimb", "pinpoint"
  ],
  "index_suffix": ["day_of_week"]        // appears after the game columns
}
```

Valid game keys: `zip`, `tango`, `queens`, `patches`, `mini_sudoku`,
`crossclimb`, `pinpoint`.
Valid index keys: `date`, `day_of_week`. Both `index_prefix` and
`index_suffix` accept any subset (or empty `[]`) in any order.

The daily writer (`sheets_updater.py`) reads the live row-1 headers and
matches them against the layout, so once `.env` points at the new sheet, any
layout change is picked up automatically — no further config edits needed.

## First Run Check

After auth setup completes, run a dry run:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
python main.py --dry-run --summary-only
```

For normal skill usage, run:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
python main.py --summary-only
```

## Troubleshooting

If `google_credentials.json` is missing, the Google OAuth step will stop and
print the expected path.

If the browser opens but Google blocks the app, check that the OAuth consent
screen is configured and that your Google account is added as a test user when
the app is in testing mode.

If Google auth works for about a week and then starts failing with an expired
or revoked token error, the OAuth app is probably still in Testing mode. Re-run
`python setup_auth.py` to create a fresh user token.

If the script raises an `AuthStoreError` about being unable to decrypt
`linkedin_state.enc` or `google_token.enc`, the Fernet master key in the OS
credential store has been removed or replaced (for example after restoring a
profile from backup, or after running on a different machine). Delete the
affected `.enc` file from the user data directory and re-run
`python setup_auth.py` to regenerate it.

On headless Linux / WSL / Docker / CI, no keyring backend is typically
available. Generate a Fernet key once and export it before running the script:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export LINKEDIN_GAMES_MASTER_KEY=<paste-key-here>
```

The same key must be reused across runs. If `$LINKEDIN_GAMES_MASTER_KEY` is
unset and no keyring is available, the script falls back to an interactive
passphrase prompt with PBKDF2; that mode is not suitable for unattended runs.

If Google Sheets returns a permission error, confirm that:

- The Google Sheets API is enabled in the same Cloud project that created the OAuth client.
- The account used during OAuth consent can access the spreadsheet.
- `SPREADSHEET_ID` in `.env` points to the intended spreadsheet.
- `WORKSHEET_NAME` exactly matches the sheet tab name.

If LinkedIn redirects to login during normal runs, the saved LinkedIn session
has expired. Re-run:

```powershell
cd C:\Users\Brian\.claude\skills\Linkedin-games\scripts
python setup_auth.py
```
