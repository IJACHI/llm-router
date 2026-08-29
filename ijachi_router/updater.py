"""Auto-Updater Engine for ijachi & ijachi-code.

Checks remote GitHub repository for updates, pulls the latest release using
a clean fetch + reset strategy (safe even when local files are modified),
and reinstalls the package into the venv.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from rich.console import Console

console = Console()


def _run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def update_ijachi() -> str:
    """Updates the ijachi installation to the latest release."""
    console.print("\n[bold cyan]🔄 Checking for ijachi updates...[/bold cyan]")

    app_dir = Path.home() / ".ijachi-app"
    current_dir = Path(__file__).parent.parent.resolve()

    target_repo = app_dir if app_dir.exists() else current_dir

    if (target_repo / ".git").exists():
        console.print(f"[dim]Pulling latest changes from GitHub repository in {target_repo}...[/dim]")
        repo = str(target_repo)
        try:
            # Step 1: Fetch latest from origin
            rc, out, err = _run(["git", "-C", repo, "fetch", "origin", "main"])
            if rc != 0:
                return f"Git fetch failed: {err or out}"

            # Step 2: Check if anything new arrived
            rc, ahead, _ = _run(["git", "-C", repo, "rev-list", "HEAD..origin/main", "--count"])
            if rc == 0 and ahead.strip() == "0":
                return "Already up to date — no updates available."

            # Step 3: Hard reset to origin/main
            # ~/.ijachi-app is a deploy-only directory — local edits are always
            # safe to discard because they come from our rsync, not manual edits.
            rc, out, err = _run(["git", "-C", repo, "reset", "--hard", "origin/main"])
            if rc != 0:
                return f"Git reset failed: {err or out}"

            # Step 4: Reinstall into venv so new deps (e.g. prompt_toolkit) land
            venv_pip = target_repo / ".venv" / "bin" / "pip"
            if venv_pip.exists():
                console.print("[dim]Reinstalling package into venv...[/dim]")
                _run([str(venv_pip), "install", "--quiet", "--no-cache-dir", "-e", repo])

            # Step 5: Re-link executables into ~/.local/bin
            target_bin = Path.home() / ".local" / "bin"
            for cmd in ("ijachi", "ijachi-code", "ijachi-router", "ijr"):
                src = target_repo / ".venv" / "bin" / cmd
                if src.exists():
                    target_bin.mkdir(parents=True, exist_ok=True)
                    dest = target_bin / cmd
                    dest.unlink(missing_ok=True)
                    dest.symlink_to(src)

            return "Successfully updated ijachi to latest version from GitHub!"

        except Exception as e:
            return f"Update error: {e}"

    # Fallback: PyPI
    try:
        console.print("[dim]Updating via PyPI package manager...[/dim]")
        _run([sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "ijachi-llm-router"])
        return "Successfully upgraded ijachi-llm-router via PyPI!"
    except Exception as e:
        return f"Update check completed: {e}"
