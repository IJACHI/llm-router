"""Layered settings for ijachi-code (later files override earlier ones):

1. ~/.ijachi-llmr/settings.json          — user
2. <repo>/.ijachi/settings.json           — project (commit this)
3. <repo>/.ijachi/settings.local.json     — personal project overrides (git-ignore this)

Schema:
{
  "permissions": {"allow": ["Bash(npm test:*)", "Edit(src/**)"], "deny": ["Bash(git push:*)"], "ask": [...]},
  "hooks": {"PreToolUse": [{"matcher": "Bash", "command": "./scripts/check.sh"}], "PostToolUse": [...]},
  "mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {}}},
  "sandbox": {"enabled": true, "network": false},
  "web": {"search_provider": "auto"}
}
List values are concatenated across layers; dict values are merged; scalars are overridden.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

USER_SETTINGS = Path.home() / ".ijachi-llmr" / "settings.json"


def _project_dir(workspace: Path) -> Path:
    from ijachi_router.context.memory import find_repo_root
    return find_repo_root(workspace) / ".ijachi"


def settings_paths(workspace: Path | str) -> list[Path]:
    proj = _project_dir(Path(workspace))
    return [USER_SETTINGS, proj / "settings.json", proj / "settings.local.json"]


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, list) and isinstance(out.get(k), list):
            out[k] = out[k] + [x for x in v if x not in out[k]]
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_settings(workspace: Path | str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for p in settings_paths(workspace):
        if p.exists():
            merged = _merge(merged, _read(p))
    return merged


def add_permission_rule(workspace: Path | str, rule: str, kind: str = "allow", scope: str = "local") -> Path:
    """Persist a permission rule. scope: 'local' (personal, default), 'project' or 'user'."""
    proj = _project_dir(Path(workspace))
    path = {"user": USER_SETTINGS, "project": proj / "settings.json"}.get(scope, proj / "settings.local.json")
    data = _read(path) if path.exists() else {}
    perms = data.setdefault("permissions", {})
    rules = perms.setdefault(kind, [])
    if rule not in rules:
        rules.append(rule)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if scope == "local":
        _ensure_gitignored(proj, "settings.local.json")
    return path


def _ensure_gitignored(proj_dir: Path, name: str) -> None:
    gi = proj_dir / ".gitignore"
    try:
        existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        if name not in existing:
            gi.write_text("\n".join([*existing, name]) + "\n", encoding="utf-8")
    except OSError:
        pass
