"""Package execution entrypoint for python -m ijachi_router.

Auto-delegates to the internal virtual environment if invoked via system Python
without manual virtualenv activation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_active_env() -> None:
    """If running in base system python, re-exec inside the local or global .venv."""
    # Check if we are outside any virtual environment (base python)
    if sys.prefix == sys.base_prefix:
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [
            repo_root / ".venv" / "bin" / "python3",
            repo_root / ".venv" / "bin" / "python",
            Path.home() / ".ijachi-app" / ".venv" / "bin" / "python3",
            Path.home() / ".ijachi-app" / ".venv" / "bin" / "python",
        ]
        for venv_py in candidates:
            if venv_py.is_file() and os.access(venv_py, os.X_OK):
                # Re-execute under the virtual environment interpreter
                os.execv(str(venv_py), [str(venv_py), "-m", "ijachi_router"] + sys.argv[1:])


_ensure_active_env()

from ijachi_router.cli.code import main

if __name__ == "__main__":
    main()
