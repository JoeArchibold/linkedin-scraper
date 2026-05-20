# Setup

This project needs two kinds of local authentication before `scripts/main.py`
can run headlessly:

1. A saved LinkedIn browser session for Playwright.
2. A Google OAuth client and user token for writing to Google Sheets.

LinkedIn session state and the Google OAuth user token are stored in the local
OS credential store through Python's `keyring` package. On Windows this usually
uses Windows Credential Manager. The Google OAuth client JSON downloaded from
Google Cloud Console remains a local bootstrap file.

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
| `scripts/auth/google_credentials.json` | OAuth client configuration downloaded from Google Cloud Console. |
| OS credential store: `linkedin-games-data-collector` / `linkedin_state` | Playwright storage state for LinkedIn, including cookies and localStorage. |
| OS credential store: `linkedin-games-data-collector` / `google_token` | Cached Google user OAuth token created after browser consent. |

The local files under `scripts/auth/` are intentionally ignored by Git. Existing
legacy `linkedin_state.json` and `google_token.json` files are imported into the
OS credential store automatically if the keyring entry is missing.

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

The script then saves Playwright's browser storage state to:

```text
OS credential store: linkedin-games-data-collector / linkedin_state
```

That keyring entry contains LinkedIn cookies and localStorage. Treat it like a
password. Any process running as your local user may be able to retrieve it
through the same credential-store API until LinkedIn expires or invalidates the
session.

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
OS credential store: linkedin-games-data-collector / google_token
```

That token is reused on later runs. If it expires and has a refresh token, the
script refreshes it automatically and saves the refreshed token back to keyring.
If it cannot be refreshed, run `python setup_auth.py` again.

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
