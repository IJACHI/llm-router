"""Fast post-edit checks whose findings are fed straight back to the model.

Only quick, local, non-networked checks run here (each bounded by a short timeout), so the
model learns about a syntax or type error in the same step that introduced it.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

_TIMEOUT_S = 15


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode == 0:
        return ""
    return (proc.stdout + proc.stderr).strip()[:3000]


def _python(path: Path, text: str, root: Path) -> list[str]:
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as e:
        return [f"SyntaxError: {e.msg} (line {e.lineno}, col {e.offset})"]
    out = []
    ruff = shutil.which("ruff")
    if ruff:
        # Only real errors (pyflakes F + syntax E9), not style.
        msg = _run([ruff, "check", "--select", "E9,F63,F7,F82", "--output-format", "concise", str(path)], root)
        if msg:
            out.append(msg)
    return out


def _javascript(path: Path, root: Path) -> list[str]:
    node = shutil.which("node")
    if not node:
        return []
    msg = _run([node, "--check", str(path)], root)
    return [msg] if msg else []


def _json(text: str) -> list[str]:
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e.msg} (line {e.lineno}, col {e.colno})"]
    return []


def _yaml(text: str) -> list[str]:
    try:
        import yaml
        yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        return [f"Invalid YAML: {e}"]
    return []


def _toml(text: str) -> list[str]:
    try:
        import tomllib
        tomllib.loads(text)
    except Exception as e:  # noqa: BLE001
        return [f"Invalid TOML: {e}"]
    return []


def check_file(path: Path, root: Path) -> list[str]:
    """Return human-readable problems found in *path* (empty list = clean or unchecked)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _python(path, text, root)
    if suffix in (".js", ".mjs", ".cjs"):
        return _javascript(path, root)
    if suffix == ".json":
        return _json(text)
    if suffix in (".yaml", ".yml"):
        return _yaml(text)
    if suffix == ".toml":
        return _toml(text)
    return []


def format_diagnostics(path_str: str, problems: list[str]) -> str:
    if not problems:
        return ""
    body = "\n".join(problems)
    return f"\n\n⚠️ Diagnostics for '{path_str}' after this change (fix these before moving on):\n{body}"
