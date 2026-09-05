# About the LinkedIn Games Data Collector:
The LinkedIn Games Data Collector is a Python script which will automatically collect 
your daily LinkedIn games scores using Playwright and BeautifulSoup.  All of the 
scores are collected into a local JSON store which will then import cleanly into Pandas or 
other similar data analysis tools, and CSV files can also be generated on demand
which can be easily imported into Google Sheets, Excel or other spreadsheets.

A `skill.md` file is also included, which will allow this script to be run as a 
Claude Code skill.  If you wish to use this as a skill, clone the repo to the
`~/.claude/skills/linkedin-games-data-collector` folder.

# Quick Start

Requires Python 3.10 or later. From the project's `scripts/` directory:

```
python setup.py                    # one-time: venv + deps + Chromium + seed config
python setup_auth.py               # one-time: log in to LinkedIn
python run.py --dry-run --summary-only
python run.py                      # collect today's scores
```

- `setup.py` is idempotent and safe to re-run; it creates a virtual environment,
  installs dependencies + the Playwright Chromium browser, and copies
  `.env.example → .env` and `config.json.sample → config.json` if they're missing.
- `setup_auth.py` opens a browser to log in; the session is stored encrypted (Fernet)
  with the key in your OS credential store. Needed once per machine.
- `run.py` is a thin cross-platform launcher that runs `collector.py` through the
  venv and passes any extra arguments through (e.g. `python run.py --update`).

If you'd rather set things up by hand (or use a different venv), the manual steps
and all configuration options are documented in `SETUP.md`.