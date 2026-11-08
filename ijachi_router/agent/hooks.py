"""User-defined hooks around tool calls (configured in settings.json under "hooks").

    "hooks": {
      "PreToolUse":  [{"matcher": "Bash", "command": "./scripts/guard.sh"}],
      "PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "command": "ruff format --quiet ."}]
    }

The hook receives JSON on stdin: {"event", "tool", "args", "workspace", ["output"]}.
Exit 0 = continue (stdout of a PostToolUse hook is shown to the model); exit 2 = block
(PreToolUse) or report a problem (PostToolUse) with stderr as the reason; any other
non-zero exit is a non-blocking warning. Hooks are the user's own commands, so they run
in the workspace without the agent's OS sandbox, with a 60-second timeout.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TIMEOUT_S = 60


@dataclass
class HookOutcome:
    blocked: bool = False
    message: str = ""


def _matching(settings: dict, event: str, tool: str) -> list[dict]:
    hooks = (settings.get("hooks") or {}).get(event) or []
    out = []
    for h in hooks:
        if not isinstance(h, dict) or not h.get("command"):
            continue
        matcher = str(h.get("matcher", "*"))
        if matcher in ("*", "") or re.fullmatch(matcher, tool):
            out.append(h)
    return out


def run_hooks(settings: dict, event: str, tool: str, args: dict[str, Any], workspace: Path, output: str | None = None) -> HookOutcome:
    hooks = _matching(settings, event, tool)
    if not hooks:
        return HookOutcome()
    payload = {"event": event, "tool": tool, "args": args, "workspace": str(workspace)}
    if output is not None:
        payload["output"] = output[:20_000]
    notes: list[str] = []
    for h in hooks:
        try:
            proc = subprocess.run(
                h["command"], shell=True, cwd=workspace, input=json.dumps(payload),
                capture_output=True, text=True, timeout=int(h.get("timeout", _TIMEOUT_S)),
            )
        except subprocess.TimeoutExpired:
            notes.append(f"hook '{h['command']}' timed out")
            continue
        except OSError as e:
            notes.append(f"hook '{h['command']}' failed to start: {e}")
            continue
        if proc.returncode == 2:
            reason = (proc.stderr or proc.stdout).strip() or "blocked by hook"
            return HookOutcome(blocked=True, message=f"{event} hook '{h['command']}': {reason}")
        if proc.returncode != 0:
            notes.append(f"hook '{h['command']}' exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:500]}")
        elif event == "PostToolUse" and proc.stdout.strip():
            notes.append(proc.stdout.strip()[:2000])
    return HookOutcome(message="\n".join(notes))
