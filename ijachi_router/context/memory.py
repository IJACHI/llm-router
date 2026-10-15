"""Project Memory (IJACHI.md) management.

Document 2.5 & FR-10:
IJACHI.md holds instructions and facts for the assistant: build and test commands, style rules,
architecture notes. It is loaded in order:
1. ~/.ijachi-llmr/IJACHI.md (user)
2. repository root / IJACHI.md
3. current subdirectory / IJACHI.md
The more specific file wins on conflict.
"""

from __future__ import annotations

import os
from pathlib import Path

_USER_MEMORY_FILE = Path.home() / ".ijachi-llmr" / "IJACHI.md"


def find_repo_root(start_dir: Path | None = None) -> Path:
    """Find repository root by looking for .git or .ijachi."""
    curr = Path(start_dir or Path.cwd()).resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / ".git").exists() or (parent / ".ijachi").exists():
            return parent
    return curr


def load_project_memory(cwd: Path | str | None = None) -> str:
    """Load layered project memory: user level, repo root, and current subdir."""
    current_dir = Path(cwd or Path.cwd()).resolve()
    repo_root = find_repo_root(current_dir)

    layers: list[str] = []

    # 1. User level (~/.ijachi-llmr/IJACHI.md)
    if _USER_MEMORY_FILE.exists():
        try:
            content = _USER_MEMORY_FILE.read_text(encoding="utf-8").strip()
            if content:
                layers.append(f"<!-- User Global Memory (~/.ijachi-llmr/IJACHI.md) -->\n{content}")
        except Exception:
            pass

    # 2. Repo root level
    root_mem = repo_root / "IJACHI.md"
    if root_mem.exists():
        try:
            content = root_mem.read_text(encoding="utf-8").strip()
            if content:
                layers.append(f"<!-- Repository Memory ({root_mem}) -->\n{content}")
        except Exception:
            pass

    # 3. Subdirectory level (if distinct from root)
    if current_dir != repo_root:
        sub_mem = current_dir / "IJACHI.md"
        if sub_mem.exists():
            try:
                content = sub_mem.read_text(encoding="utf-8").strip()
                if content:
                    layers.append(f"<!-- Subdirectory Memory ({sub_mem}) -->\n{content}")
            except Exception:
                pass

    return "\n\n".join(layers)


class LayeredMemory:
    """Container for layered project memory."""

    def __init__(self, content: str):
        self.content = content

    def render_for_prompt(self) -> str:
        return self.content


def load_layered_memory(workspace_path: Path | str | None = None) -> LayeredMemory:
    """Load layered project memory and wrap in LayeredMemory container."""
    text = load_project_memory(cwd=workspace_path)
    return LayeredMemory(text)


def init_project_memory(target_dir: Path | str | None = None, auto: bool = False) -> Path:
    """Draft a new IJACHI.md in the target directory."""
    dir_path = Path(target_dir or Path.cwd()).resolve()
    mem_path = dir_path / "IJACHI.md"

    if mem_path.exists() and not auto:
        return mem_path

    # Detect project info
    has_pyproject = (dir_path / "pyproject.toml").exists()
    has_package_json = (dir_path / "package.json").exists()
    has_cargo = (dir_path / "Cargo.toml").exists()
    has_go = (dir_path / "go.mod").exists()

    build_cmd = "make test"
    if has_pyproject:
        build_cmd = "pytest"
    elif has_package_json:
        build_cmd = "npm test"
    elif has_cargo:
        build_cmd = "cargo test"
    elif has_go:
        build_cmd = "go test ./..."

    content = f"""# IJACHI.md — Project Memory for {dir_path.name}

## Project Overview
- **Name:** {dir_path.name}
- **Primary Language / Stack:** {'Python' if has_pyproject else 'JavaScript/TypeScript' if has_package_json else 'General'}

## Common Commands
- **Test:** `{build_cmd}`
- **Lint / Format:** `make lint` or package default

## Coding Guidelines
- Maintain existing codebase conventions and documentation integrity.
- Never write destructive file commands or push without approval.
- Ensure all automated unit and integration tests pass before completing tasks.
"""
    mem_path.write_text(content, encoding="utf-8")
    return mem_path
