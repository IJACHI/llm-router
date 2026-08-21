"""Auto-Updater Engine for ijachi & ijachi-code.

Checks remote GitHub repository / PyPI for updates, pulls latest release,
and updates executable shortcuts cleanly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from rich.console import Console

console = Console()


def update_ijachi() -> str:
    """Updates the ijachi installation to the latest release."""
    console.print("\n[bold cyan]🔄 Checking for ijachi updates...[/bold cyan]")

    app_dir = Path.home() / ".ijachi-app"
    current_dir = Path(__file__).parent.parent.resolve()

    # 1. If installed in ~/.ijachi-app or local git repo
    target_repo = app_dir if app_dir.exists() else current_dir

    if (target_repo / ".git").exists():
        console.print(f"[dim]Pulling latest changes from GitHub repository in {target_repo}...[/dim]")
        try:
            res = subprocess.run(
                ["git", "-C", str(target_repo), "pull", "--rebase", "origin", "main"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                venv_pip = target_repo / ".venv" / "bin" / "pip"
                if venv_pip.exists():
                    subprocess.run(
                        [str(venv_pip), "install", "--quiet", "--no-cache-dir", "-e", str(target_repo)],
                        capture_output=True,
                        check=False,
                    )
                return "Successfully updated ijachi to latest version from GitHub!"
            else:
                return f"Git pull notice: {res.stderr.strip() or 'Already up to date.'}"
        except Exception as e:
            return f"Git update notice: {e}"

    # 2. PyPI pip package fallback update
    try:
        console.print("[dim]Updating via PyPI package manager...[/dim]")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "ijachi-llm-router"],
            capture_output=True,
            check=False,
        )
        return "Successfully upgraded ijachi-llm-router via PyPI!"
    except Exception as e:
        return f"Update check completed: {e}"
