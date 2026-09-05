"""
Bootstrap the LinkedIn Games data collector for a new machine.

Creates (or reuses) a virtual environment, installs the Python dependencies and
the Playwright Chromium browser, and seeds `.env` / `config.json` from the
shipped samples the first time they're missing. It never overwrites an existing
`.env` or `config.json`, so re-running it is safe and idempotent.

Usage (from the project's `scripts/` directory):

    python setup.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REQS = SCRIPTS_DIR / "requirements.txt"
# Both are git-ignored; `venv` exists in some older checkouts while `.venv` is
# the name the docs recommend. Reuse whichever is already there.
VENV_NAMES = ("venv", ".venv")


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _existing_venv() -> Path | None:
    for name in VENV_NAMES:
        candidate = SCRIPTS_DIR / name
        for rel in ("Scripts/python.exe", "bin/python"):
            if (candidate / rel).exists():
                return candidate
    return None


def _run(args: list) -> None:
    print("  " + " ".join(str(a) for a in args))
    subprocess.check_call(args)


def _copy_if_missing(src: Path, dst: Path) -> None:
    if dst.exists():
        print(f"  {dst.name} already exists - leaving it untouched.")
        return
    shutil.copyfile(src, dst)
    print(f"  created {dst.name} from {src.name}")


def main() -> int:
    print("Setting up the LinkedIn Games data collector ...")

    venv_dir = _existing_venv()
    if venv_dir is None:
        venv_dir = SCRIPTS_DIR / ".venv"
        print(f"Creating virtual environment: {venv_dir.relative_to(SCRIPTS_DIR)}")
        _run([sys.executable, "-m", "venv", str(venv_dir)])
    else:
        print(
            "Using existing virtual environment: "
            f"{venv_dir.relative_to(SCRIPTS_DIR)}"
        )

    py = _venv_python(venv_dir)

    print("Installing Python dependencies ...")
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    _run([str(py), "-m", "pip", "install", "-r", str(REQS), "-q"])

    print("Installing Playwright Chromium browser ...")
    _run([str(py), "-m", "playwright", "install", "chromium"])

    print("Seeding config files ...")
    _copy_if_missing(SCRIPTS_DIR / ".env.example", SCRIPTS_DIR / ".env")
    _copy_if_missing(
        SCRIPTS_DIR / "config.json.sample", SCRIPTS_DIR / "config.json"
    )

    if sys.platform.startswith("linux"):
        print(
            "On Debian/Ubuntu you may still need: "
            f"{str(_venv_python(venv_dir))} -m playwright install-deps chromium "
            "(this needs sudo)."
        )

    print()
    print("Done. Next steps:")
    print("  1. Log in to LinkedIn once:      python setup_auth.py")
    print("  2. Check it works:               python run.py --dry-run --summary-only")
    print("  3. Run the daily collection:     python run.py")
    print()
    print("config.json is the main per-machine file (see SETUP.md). The .env file")
    print("is only needed to push results to the leaderboard API (LEADERBOARD_API_URL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
