"""Permission rules: ``Tool``, ``Tool(spec)``.

- ``Bash(npm test:*)``  — command prefix; ``Bash(make lint)`` — exact command.
  A compound command (&&, ;, |) matches only if *every* segment matches.
- ``Edit(src/**)`` / ``Write(*.md)`` / ``Read(docs/**)`` — workspace-relative path globs
  (``Edit`` rules also cover ``MultiEdit``).
- ``WebFetch(domain:docs.python.org)`` — host (subdomains included).
- ``mcp__github__*`` / ``mcp__github__create_issue`` — MCP tools.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_RULE_RE = re.compile(r"^([A-Za-z_][\w*]*)(?:\((.*)\))?$", re.S)
_FILE_TOOLS = {"Read": "Read", "Edit": "Edit", "MultiEdit": "Edit", "Write": "Write",
               "read_file": "Read", "edit_file": "Edit", "write_file": "Write"}
# Commands whose first *two* words identify the action (npm test, git push, cargo build...).
_TWO_WORD = {"npm", "pnpm", "yarn", "bun", "npx", "git", "cargo", "go", "pip", "pip3", "uv", "poetry", "docker",
             "kubectl", "make", "dotnet", "gradle", "mvn", "brew", "python", "python3", "node", "deno", "gh", "rails",
             "bundle", "mix", "terraform", "helm", "pytest"}


def parse_rule(rule: str) -> tuple[str, str | None]:
    m = _RULE_RE.match(rule.strip())
    if not m:
        return rule.strip(), None
    return m.group(1), m.group(2)


def _bash_segment_matches(spec: str, segment: str) -> bool:
    if spec.endswith(":*"):
        prefix = spec[:-2].strip()
        return segment == prefix or segment.startswith(prefix + " ")
    return segment == spec.strip()


def _path_matches(spec: str, path: str, workspace: Path) -> bool:
    p = Path(path)
    try:
        rel = (p if p.is_absolute() else (workspace / p)).resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return False  # outside the workspace: path rules never grant access there
    spec = spec.lstrip("./")
    if spec.endswith("/**"):
        base = spec[:-3]
        return rel == base or rel.startswith(base + "/")
    return fnmatch.fnmatch(rel, spec) or fnmatch.fnmatch(Path(rel).name, spec)


def rule_matches(rule: str, tool: str, args: dict[str, Any], workspace: Path) -> bool:
    from ijachi_router.agent.permissions import _split_shell_segments

    name, spec = parse_rule(rule)
    if "*" in name:  # e.g. mcp__github__*
        return fnmatch.fnmatch(tool, name)
    canonical = _FILE_TOOLS.get(tool, tool)
    if tool in ("Bash", "run_command"):
        canonical = "Bash"
    if name != canonical and name != tool:
        return False
    if spec is None or spec in ("", "*"):
        return True
    if canonical == "Bash":
        segments = _split_shell_segments(str(args.get("command", "")))
        return bool(segments) and all(_bash_segment_matches(spec, seg) for seg in segments)
    if canonical in ("Read", "Edit", "Write"):
        return _path_matches(spec, str(args.get("path", "")), workspace)
    if canonical == "WebFetch" and spec.startswith("domain:"):
        host = (urlparse(str(args.get("url", ""))).hostname or "").lower()
        want = spec[len("domain:"):].lower()
        return host == want or host.endswith("." + want)
    return False


def any_match(rules: list[str], tool: str, args: dict[str, Any], workspace: Path) -> str | None:
    for r in rules:
        if rule_matches(r, tool, args, workspace):
            return r
    return None


def suggest_rule(tool: str, args: dict[str, Any], workspace: Path) -> str:
    """The narrowest useful rule for 'allow this again' (shown in the approval prompt)."""
    if tool in ("Bash", "run_command"):
        from ijachi_router.agent.permissions import _split_shell_segments

        segments = _split_shell_segments(str(args.get("command", "")))
        first = segments[0] if segments else ""
        try:
            words = shlex.split(first)
        except ValueError:
            words = first.split()
        if not words:
            return "Bash"
        n = 2 if words[0] in _TWO_WORD and len(words) > 1 and not words[1].startswith("-") else 1
        if words[0] in ("python", "python3") and len(words) > 2 and words[1] == "-m":
            n = 3
        return f"Bash({' '.join(words[:n])}:*)"
    canonical = _FILE_TOOLS.get(tool)
    if canonical:
        p = Path(str(args.get("path", "")))
        try:
            rel = (p if p.is_absolute() else workspace / p).resolve().relative_to(workspace.resolve())
            parent = rel.parent.as_posix()
        except (ValueError, OSError):
            return canonical
        return f"{canonical}({parent}/**)" if parent not in ("", ".") else f"{canonical}(*)"
    if tool == "WebFetch":
        host = urlparse(str(args.get("url", ""))).hostname
        return f"WebFetch(domain:{host})" if host else "WebFetch"
    return tool
