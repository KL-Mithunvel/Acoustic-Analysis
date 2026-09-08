"""``python -m acoustic_analysis`` launches the GUI; falls back to the CLI help
until the GUI is built.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from .app.main_window import run
    except ImportError:
        print(
            "The GUI is not available yet. Use the command line instead:\n"
            "    python -m acoustic_analysis.cli --help",
            file=sys.stderr,
        )
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
