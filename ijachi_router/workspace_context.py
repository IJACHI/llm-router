"""Workspace Context Loader for ijachi-code.

Automatically discovers IJACHI.md, CLAUDE.md, or AGENTS.md in the working
directory and injects it as workspace-level context into every agent session.

On first run in a new workspace, offers to auto-generate IJACHI.md from
detected stack, language, test commands, and conventions — eliminating the
#1 Claude Code pain point: having to re-brief the AI every session.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

console = Console()

_CONTEXT_FILES = ["IJACHI.md", "CLAUDE.md", "AGENTS.md", ".ijachi"]


def load_workspace_context(cwd: Path | str | None = None) -> str | None:
    """Search for a workspace context file and return its content."""
    cwd = Path(cwd or Path.cwd()).resolve()

    # Walk up directory tree (max 3 levels)
    search = [cwd] + list(cwd.parents)[:3]
    for directory in search:
        for filename in _CONTEXT_FILES:
            candidate = directory / filename
            if candidate.exists() and candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8").strip()
                    if content:
                        return f"[Workspace Context from {filename}]\n{content}"
                except Exception:
                    pass
    return None


def detect_workspace_info(cwd: Path) -> dict:
    """Detect programming language, package manager, test runner, and git info."""
    info = {}

    # Language detection
    if (cwd / "pyproject.toml").exists() or (cwd / "requirements.txt").exists() or (cwd / "setup.py").exists():
        info["language"] = "Python"
        info["package_manager"] = "pip / uv"
        info["test_command"] = "pytest"
    elif (cwd / "package.json").exists():
        info["language"] = "JavaScript / TypeScript"
        info["package_manager"] = "npm"
        info["test_command"] = "npm test"
    elif (cwd / "Cargo.toml").exists():
        info["language"] = "Rust"
        info["package_manager"] = "cargo"
        info["test_command"] = "cargo test"
    elif (cwd / "go.mod").exists():
        info["language"] = "Go"
        info["package_manager"] = "go modules"
        info["test_command"] = "go test ./..."
    else:
        info["language"] = "Unknown"
        info["package_manager"] = "unknown"
        info["test_command"] = "unknown"

    # Git remote
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True, cwd=cwd, timeout=3,
        ).strip()
        info["git_remote"] = remote
    except Exception:
        info["git_remote"] = "none"

    # Top-level directories
    dirs = [d.name for d in cwd.iterdir() if d.is_dir() and not d.name.startswith(".")][:10]
    info["directories"] = ", ".join(dirs)

    return info


def generate_workspace_context(cwd: Path | str | None = None, auto: bool = False) -> str | None:
    """
    Offer to auto-generate IJACHI.md if none exists.
    Returns path to created file or None if skipped.
    """
    cwd = Path(cwd or Path.cwd()).resolve()

    # Skip if context already exists
    existing = load_workspace_context(cwd)
    if existing:
        return None

    if not auto:
        console.print(
            "[bold cyan]💡 No IJACHI.md found in this workspace.[/bold cyan]\n"
            "   Auto-generating one will give ijachi-code persistent context about your project."
        )
        if not Confirm.ask("Generate IJACHI.md now?", default=True):
            return None

    console.print("[dim]Scanning workspace...[/dim]")
    info = detect_workspace_info(cwd)

    content = f"""# IJACHI Workspace Context

## Project Overview
- **Language**: {info.get('language', 'Unknown')}
- **Package Manager**: {info.get('package_manager', 'unknown')}
- **Test Command**: `{info.get('test_command', 'unknown')}`
- **Git Remote**: {info.get('git_remote', 'none')}

## Directory Structure
Key directories: `{info.get('directories', '')}`

## Conventions
- Always run tests after making changes
- Follow existing code style and patterns
- Use conventional commits (feat/fix/chore/docs)
- Never remove existing docstrings or comments

## Notes
(Add project-specific notes here for ijachi-code to always remember)
"""

    target = cwd / "IJACHI.md"
    target.write_text(content, encoding="utf-8")
    console.print(f"[bold green]✓ Created[/bold green] [cyan]{target}[/cyan]")
    console.print("[dim]Edit IJACHI.md to add project-specific conventions and rules.[/dim]\n")
    return str(target)
