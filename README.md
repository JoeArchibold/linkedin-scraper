# About the LinkedIn Games Data Collector:
The LinkedIn Games Data Collector is a Python script which will automatically collect 
your daily LinkedIn games scores using Playwright and BeautifulSoup.  All of the 
scores are ollected into a local JSON store which will then import cleanly into Pandas or 
other similar data analysis tools, and CSV files can also be generated on demand
which can be easily imported into Google Sheets, Excel or other spreadsheets.

A `skill.md` file is also included, which will allow this script to be run as a 
Claude Code skill.  If you wish to use this as a skill, clone the repo to the
`~/.claude/skills/linkedin-games-data-collector` folder.

# Quick Start
This script requires Python 3.10 or later to run.  Using a virtual environment (VENV)
is highly recommended.  

* Clone the repo to any folder and run the following commands to install dependencies:
```
pip install -r requirements.txt
playwright install chromium
```

For headless operation, it will be necessary to manually log into LinkedIn in the
Chromium browser one time using the following command:

```
python setup_auth.py
```
Your LinkedIn session token will be stored encrypted using [Fernet Encryption](https://pypi.org/project/FernetEncryption/), with the 
decryption key located in your operating system's credential store.  

## Running the script
To verify that the script is running properly, use the following command:
```
python collector.py --dry-run
```

For full instructions and documentation of the available configuration options, see the
`SETUP.md` file.