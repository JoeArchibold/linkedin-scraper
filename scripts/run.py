"""
Run the linkedin-games collector scripts using the local virtual environment.

Makes launching the collector (and the other `scripts/` entry points) a single
command, cross-platform, so users don't need to activate a venv or remember the
interpreter path.

If the first argument names a `.py` script in this directory (with or without
the extension), it is run inside the venv; otherwise `collector.py` is run with
all arguments passed through.

Usage (from the project's `scripts/` directory):

    python run.py [script-name] [args...]

Examples:
    python run.py                      # collector in smart mode
    python run.py --dry-run --summary-only
    python run.py --update
    python run.py setup_auth           # one-time LinkedIn login
    python run.py export_csv           # regenerate the CSV view
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


def _resolve_target(args: list[str]) -> tuple[Path, list[str]]:
    if args and not args[0].startswith("-"):
        candidate = SCRIPTS_DIR / f"{args[0]}.py"
        if candidate.exists():
            return candidate, args[1:]
        alt = SCRIPTS_DIR / args[0]
        if alt.exists() and alt.suffix == ".py":
            return alt, args[1:]
    return COLLECTOR, args


def main() -> int:
    py = _venv_python()
    if py is None:
        print(
            "No virtual environment found. Run setup first:\n"
            "    python setup.py",
            file=sys.stderr,
        )
        return 1
    target, rest = _resolve_target(sys.argv[1:])
    return subprocess.call([str(py), str(target), *rest])


if __name__ == "__main__":
    sys.exit(main())
