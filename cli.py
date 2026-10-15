import os
import sys
from pathlib import Path


def _ensure_active_env() -> None:
    """If running in base system python, re-exec inside the local or global .venv."""
    if sys.prefix == sys.base_prefix:
        repo_root = Path(__file__).resolve().parent
        candidates = [
            repo_root / ".venv" / "bin" / "python3",
            repo_root / ".venv" / "bin" / "python",
            Path.home() / ".ijachi-app" / ".venv" / "bin" / "python3",
            Path.home() / ".ijachi-app" / ".venv" / "bin" / "python",
        ]
        for venv_py in candidates:
            if venv_py.is_file() and os.access(venv_py, os.X_OK):
                os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve())] + sys.argv[1:])


_ensure_active_env()

from ijachi_router.cli.code import main as code_main
from ijachi_router.cli.router import main as router_main

# Backward-compatible main
main = router_main

if __name__ == "__main__":
    main()

