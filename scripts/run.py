"""
Run the LinkedIn Games data collector using the local virtual environment.

Makes launching `collector.py` a single command (and cross-platform), so users
don't need to activate a venv or remember the interpreter path. Any arguments
are passed straight through to `collector.py`.

Usage (from the project's `scripts/` directory):

    python run.py [collector arguments...]

Examples:
    python run.py --dry-run --summary-only
    python run.py
    python run.py --update
"""

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
COLLECTOR = SCRIPTS_DIR / "collector.py"


def _venv_python() -> Path | None:
    for name in ("venv", ".venv"):
        base = SCRIPTS_DIR / name
        for rel in ("Scripts/python.exe", "bin/python"):
            candidate = base / rel
            if candidate.exists():
                return candidate
    return None


def main() -> int:
    py = _venv_python()
    if py is None:
        print(
            "No virtual environment found. Run setup first:\n"
            "    python setup.py",
            file=sys.stderr,
        )
        return 1
    return subprocess.call([str(py), str(COLLECTOR), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
