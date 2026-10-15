import os
import sys
from pathlib import Path

# If invoked via python3 -m ijachi_router in base system python, delegate to local or global venv
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
            # Only re-exec if this was invoked as a command/module execution
            if "-m" in sys.argv or any("ijachi" in str(arg) for arg in sys.argv):
                os.execv(str(venv_py), [str(venv_py), "-m", "ijachi_router"] + sys.argv[1:])

from ijachi_router.core import route, Router

__version__ = "0.1.0"
__all__ = ["route", "Router"]

