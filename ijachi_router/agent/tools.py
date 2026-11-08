"""Workspace Tools Runtime with atomic edits, checkpoints, and schema validation.

Document 2.3 (FR-01, FR-02, FR-03, FR-04, FR-05):
- Tool set: Read, Edit, Write, Glob, Grep, ListDir, Bash, Plan/Todo.
- JSON schema validation before execution (malformed calls returned as error to model).
- Atomic file edits that fail if file changed since last read (FR-03 stale read check).
- File checkpoints created before first write of each turn.
- Subprocess environment scrubbed and output capped (FR-04, FR-05).
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ijachi_router.agent.diagnostics import check_file, format_diagnostics
from ijachi_router.agent.sandbox import WorkspaceSandbox

if TYPE_CHECKING:
    from ijachi_router.session.checkpoints import CheckpointManager
    from ijachi_router.session.state import PlanStep, SessionState


_SKIP_DIRS = {"node_modules", "venv", "__pycache__", "dist", "build"}
_GREP_LIMIT = 80
# Commands that legitimately need the network (they already require approval or a rule).
_NETWORK_CMD_RE = re.compile(
    r"\b(pip3?|uv|poetry|npm|pnpm|yarn|bun|npx|cargo|go|gem|bundle|composer|brew|apt(-get)?|curl|wget)\s+"
    r"(install|add|get|update|upgrade|sync|fetch|download|ci|i\b)|\bgit\s+(clone|fetch|pull|push)\b|\b(curl|wget)\b"
)
_SENSITIVE_GLOBS = (".env*", "*.pem", "*.key", "id_rsa*", "id_ed25519*")


def atomic_write(path: Path, content: str) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written file."""
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _line_spans(text: str, needle_lines: list[str]) -> list[tuple[int, int]]:
    """Character spans where consecutive lines equal *needle_lines* after stripping whitespace."""
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))
    n = len(needle_lines)
    spans = []
    for i in range(len(lines) - n + 1):
        if all(lines[i + k].strip() == needle_lines[k] for k in range(n)):
            spans.append((offsets[i], offsets[i + n]))
    return spans


def apply_edit(text: str, target: str, replacement: str, replace_all: bool = False) -> tuple[str, str | None]:
    """Replace *target* with *replacement* in *text*.

    Returns (new_text, None) or (text, error). Ambiguity is an error: if the target occurs
    more than once and replace_all is false, nothing changes and the model is asked for more
    context — silently editing the first occurrence is how agents corrupt code.
    """
    if not target:
        return text, "target_content is empty"
    if target == replacement:
        return text, "target_content and replacement_content are identical"
    norm_text = text.replace("\r\n", "\n")
    norm_target = target.replace("\r\n", "\n")
    norm_repl = replacement.replace("\r\n", "\n")
    count = norm_text.count(norm_target)
    if count:
        if count > 1 and not replace_all:
            return text, (
                f"target_content matches {count} places. Include more surrounding lines so it is unique, "
                "or set replace_all to true to change every occurrence"
            )
        base = text if text.count(target) == count else norm_text
        t, r = (target, replacement) if base is text else (norm_target, norm_repl)
        return base.replace(t, r) if replace_all else base.replace(t, r, 1), None

    # Whitespace-tolerant fallback, only when it identifies exactly one location.
    needle = [ln.strip() for ln in norm_target.strip("\n").splitlines()]
    if not needle or not any(needle):
        return text, "target_content not found. Read the file and copy the exact text"
    spans = _line_spans(norm_text, needle)
    if len(spans) == 1:
        start, end = spans[0]
        block = norm_text[start:end]
        repl = _reindent(norm_repl, norm_target, block)
        repl = repl if repl.endswith("\n") or not block.endswith("\n") else repl + "\n"
        return norm_text[:start] + repl + norm_text[end:], None
    if len(spans) > 1:
        return text, f"target_content matches {len(spans)} places (ignoring indentation). Include more surrounding lines so it is unique"
    hint = closest_snippet(norm_text, norm_target)
    return text, "target_content not found. Read the file and copy the exact text (including indentation)" + (
        f". The closest text in the file is:\n{hint}" if hint else ""
    )


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _reindent(replacement: str, target: str, matched_block: str) -> str:
    """Shift replacement lines by the indentation difference between the model's target and
    the text actually matched, so a whitespace-tolerant match cannot break Python indentation."""
    t_lines = [l for l in target.splitlines() if l.strip()]
    m_lines = [l for l in matched_block.splitlines() if l.strip()]
    if not t_lines or not m_lines:
        return replacement
    have, want = _indent(t_lines[0]), _indent(m_lines[0])
    if have == want:
        return replacement
    out = []
    for line in replacement.splitlines(keepends=True):
        if not line.strip():
            out.append(line)
        elif line.startswith(have):
            out.append(want + line[len(have):])
        else:
            out.append(want + line.lstrip(" \t"))
    return "".join(out)


def closest_snippet(text: str, target: str, max_lines: int = 12) -> str:
    """Numbered lines of *text* most similar to *target* (helps the model correct itself)."""
    import difflib

    lines = text.splitlines()
    t_lines = [l for l in target.splitlines() if l.strip()] or [target]
    n = max(1, min(len(t_lines), max_lines))
    best, best_i = 0.0, -1
    t_join = "\n".join(l.strip() for l in t_lines)
    for i in range(0, max(1, len(lines) - n + 1)):
        window = "\n".join(l.strip() for l in lines[i:i + n])
        r = difflib.SequenceMatcher(None, t_join, window).quick_ratio()
        if r > best:
            r = difflib.SequenceMatcher(None, t_join, window).ratio()
            if r > best:
                best, best_i = r, i
    if best_i < 0 or best < 0.3:
        return ""
    lo, hi = max(0, best_i - 1), min(len(lines), best_i + n + 1)
    return "\n".join(f"{k + 1:4d} | {lines[k]}" for k in range(lo, hi))


@dataclass
class ToolExecutionResult:
    success: bool
    output: str
    error: str | None = None
    diff: str | None = None


# JSON schemas for tools validation (FR-02)
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "Read": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    },
    "Edit": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "target_content": {"type": "string"},
            "replacement_content": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "target_content", "replacement_content"],
    },
    "MultiEdit": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "edits": {"type": "array"},
        },
        "required": ["path", "edits"],
    },
    "Write": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    "Glob": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
    },
    "Grep": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string"},
            "glob": {"type": "string"},
        },
        "required": ["query"],
    },
    "RepoMap": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    },
    "Explore": {
        "type": "object",
        "properties": {"task": {"type": "string"}},
        "required": ["task"],
    },
    "ListDir": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
    },
    "Bash": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "run_in_background": {"type": "boolean"},
            "timeout": {"type": "integer"},
        },
        "required": ["command"],
    },
    "BashOutput": {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    },
    "KillShell": {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    },
    "WebFetch": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    "WebSearch": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    "Plan": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {"type": "array"},
        },
    },
}


_TOOL_DESCRIPTIONS: dict[str, str] = {
    "Read": "Read a text file in the workspace. Output has line numbers. Use start_line/end_line for large files.",
    "Edit": "Replace exact text in an existing file. target_content must match the current file and be unique "
            "(include surrounding lines), or set replace_all to change every occurrence. Read the file first.",
    "MultiEdit": "Apply several exact-text edits to ONE file in a single atomic step (all succeed or none are written). "
                 "Each edit: {target_content, replacement_content, replace_all?}. Edits apply in order.",
    "Write": "Create a file or overwrite it entirely with content. Prefer Edit for small changes to existing files.",
    "Glob": "List workspace files matching a glob pattern such as 'src/**/*.py'.",
    "Grep": "Search file contents in the workspace with a regular expression (case-insensitive).",
    "RepoMap": "Outline of the codebase: files with their classes, functions and signatures. Use it first to find "
               "where things live; pass a subdirectory path for detail on large repos.",
    "Explore": "Delegate a read-only investigation (e.g. 'find where auth tokens are validated and summarise the flow') "
               "to a fast helper agent. Returns its findings. Several Explore calls in one step run in parallel.",
    "ListDir": "List the entries of a workspace directory.",
    "Bash": "Run a shell command in the workspace root (non-interactive; default timeout 120s, max 600). Each call "
            "is a fresh shell. For servers/watchers/long jobs set run_in_background and poll with BashOutput.",
    "BashOutput": "Read new output (and status) of a background shell started with Bash run_in_background.",
    "KillShell": "Stop a background shell.",
    "WebFetch": "Fetch a public web page (docs, issues, changelogs) and return it as text.",
    "WebSearch": "Search the web. Returns titles, URLs and snippets; follow up with WebFetch.",
    "Plan": "Record a multi-step plan (goal + ordered steps). The system then walks you through each step.",
}
_PARAM_DESCRIPTIONS: dict[str, str] = {
    "path": "Path relative to the workspace root",
    "start_line": "First line to read (1-based)",
    "end_line": "Last line to read (inclusive)",
    "target_content": "Exact existing text to replace",
    "replacement_content": "New text",
    "replace_all": "Replace every occurrence instead of requiring a unique match",
    "edits": "List of {target_content, replacement_content, replace_all?} objects",
    "content": "Full file contents",
    "pattern": "Glob pattern",
    "query": "Regex (Grep) or search terms (WebSearch)",
    "command": "Shell command",
    "run_in_background": "Start and return immediately (servers, watchers, long-running jobs)",
    "timeout": "Seconds before the command is killed (max 600)",
    "id": "Background shell id",
    "url": "http(s) URL",
    "goal": "Overall goal",
    "task": "What to investigate and what to report back",
    "glob": "Only search files matching this glob, e.g. '*.py'",
    "steps": "Ordered step titles",
}


_ARRAY_ITEMS: dict[str, dict[str, Any]] = {
    "edits": {
        "type": "object",
        "properties": {
            "target_content": {"type": "string"},
            "replacement_content": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["target_content", "replacement_content"],
    },
}


def native_tool_specs() -> list[dict[str, Any]]:
    """Tool definitions for providers' native tool-calling APIs (neutral format)."""
    specs = []
    for name, schema in TOOL_SCHEMAS.items():
        props = {}
        for pname, pschema in schema.get("properties", {}).items():
            prop = dict(pschema)
            if prop.get("type") == "array":
                prop["items"] = _ARRAY_ITEMS.get(pname, {"type": "string"})
            if pname in _PARAM_DESCRIPTIONS:
                prop["description"] = _PARAM_DESCRIPTIONS[pname]
            props[pname] = prop
        specs.append({
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "parameters": {"type": "object", "properties": props, "required": list(schema.get("required", []))},
        })
    return specs


def validate_tool_args(tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
    """Validate tool call arguments against schema (FR-02)."""
    schema = TOOL_SCHEMAS.get(tool_name)
    if not schema:
        # Check alias
        alias_map = {
            "read_file": "Read",
            "edit_file": "Edit",
            "write_file": "Write",
            "list_dir": "ListDir",
            "grep_search": "Grep",
            "run_command": "Bash",
        }
        mapped = alias_map.get(tool_name)
        if mapped:
            schema = TOOL_SCHEMAS.get(mapped)

    if not schema:
        return False, f"Unknown tool: '{tool_name}'"

    required = schema.get("required", [])
    for field in required:
        if field not in args:
            return False, f"Missing required parameter '{field}' for tool '{tool_name}'"

    return True, "Valid"


class ToolRuntime:
    """Executes validated workspace tools with state updates and checkpointing."""

    def __init__(self, sandbox: WorkspaceSandbox, state: "SessionState", checkpoints: "CheckpointManager"):
        self.sandbox = sandbox
        self.state = state
        self.checkpoints = checkpoints
        self.turn_checkpoints_created: set[str] = set()
        self.turn_checkpoint_id: str | None = None
        self.turn_label: str = ""

    def begin_turn(self, label: str = "") -> None:
        """Start a new change set: all files modified until the next call form one /undo unit."""
        self.turn_checkpoints_created = set()
        self.turn_checkpoint_id = None
        self.turn_label = label

    def _ensure_checkpoint_for_file(self, target_path: Path) -> None:
        """Snapshot a file before its first modification in this turn (FR-03)."""
        p_str = str(target_path)
        if p_str in self.turn_checkpoints_created:
            return
        if self.turn_checkpoint_id is None:
            name = f"Turn changes: {self.turn_label[:60]}" if self.turn_label else f"Pre-edit checkpoint for {target_path.name}"
            self.turn_checkpoint_id = self.checkpoints.create_checkpoint(name, [target_path])
        else:
            self.checkpoints.add_to_checkpoint(self.turn_checkpoint_id, [target_path])
        self.turn_checkpoints_created.add(p_str)

    def execute(self, tool_name: str, args: dict[str, Any]) -> ToolExecutionResult:
        # Normalize tool names
        normalized_name = {
            "read_file": "Read",
            "edit_file": "Edit",
            "write_file": "Write",
            "list_dir": "ListDir",
            "grep_search": "Grep",
            "run_command": "Bash",
            "plan": "Plan",
        }.get(tool_name, tool_name)

        # Validate schema (FR-02)
        valid, val_err = validate_tool_args(normalized_name, args)
        if not valid:
            return ToolExecutionResult(success=False, output="", error=val_err)

        method = getattr(self, f"tool_{normalized_name.lower()}", None)
        if not method:
            return ToolExecutionResult(success=False, output="", error=f"Tool implementation not found: '{tool_name}'")

        try:
            return method(args)
        except Exception as e:
            return ToolExecutionResult(success=False, output="", error=f"Tool error: {e}")

    # ── Tool Implementations ────────────────────────────────────────────────

    def tool_read(self, args: dict[str, Any]) -> ToolExecutionResult:
        path_str = args.get("path", "")
        start_line = args.get("start_line")
        end_line = args.get("end_line")

        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        if self.sandbox.is_sensitive_file(target):
            return ToolExecutionResult(success=False, output="", error=f"Access denied to sensitive file '{path_str}'")

        if not target.exists() or not target.is_file():
            return ToolExecutionResult(success=False, output="", error=f"File not found: '{path_str}'{self._suggest_paths(path_str)}")

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            self.state.record_file_read(str(target))
            lines = content.splitlines()
            total = len(lines)
            s_idx = max(0, start_line - 1) if start_line else 0
            e_idx = min(total, end_line) if end_line else total
            sliced = lines[s_idx:e_idx]
            numbered = [f"{i + s_idx + 1:4d} | {line}" for i, line in enumerate(sliced)]
            output = f"File: {path_str} (lines {s_idx + 1}-{e_idx} of {total})\n" + "\n".join(numbered)
            return ToolExecutionResult(success=True, output=output)
        except Exception as e:
            return ToolExecutionResult(success=False, output="", error=f"Error reading file: {e}")

    def _suggest_paths(self, path_str: str, limit: int = 5) -> str:
        """' Did you mean: ...' for workspace files with the same name (cheap, bounded walk)."""
        name = Path(path_str).name
        if not name:
            return ""
        hits: list[str] = []
        root = self.sandbox.primary_root
        for i, p in enumerate(root.rglob(name)):
            if i > 2000 or len(hits) >= limit:
                break
            rel = p.relative_to(root)
            if p.is_file() and not any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts):
                hits.append(str(rel))
        return f". Did you mean: {', '.join(hits)}?" if hits else ""

    def _load_for_edit(self, path_str: str) -> tuple[Path | None, str | None, ToolExecutionResult | None]:
        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return None, None, ToolExecutionResult(success=False, output="", error=str(e))
        if not target.exists():
            return target, None, None
        if self.state.check_stale_read(str(target)):
            return None, None, ToolExecutionResult(
                success=False,
                output="",
                error=f"Stale file error: '{path_str}' changed on disk since it was last read. Please re-read the file first.",
            )
        return target, target.read_text(encoding="utf-8", errors="replace"), None

    def _commit_edit(self, target: Path, path_str: str, existing: str, new_content: str, summary: str) -> ToolExecutionResult:
        self._ensure_checkpoint_for_file(target)
        atomic_write(target, new_content)
        self.state.record_file_write(str(target))
        diff = "".join(difflib.unified_diff(
            existing.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
        ))
        notes = format_diagnostics(path_str, check_file(target, self.sandbox.primary_root))
        return ToolExecutionResult(success=True, output=summary + notes, diff=diff)

    def tool_edit(self, args: dict[str, Any]) -> ToolExecutionResult:
        path_str = args.get("path", "")
        target_content = args.get("target_content", "")
        replacement_content = args.get("replacement_content", "")
        replace_all = bool(args.get("replace_all", False))

        target, existing, err = self._load_for_edit(path_str)
        if err:
            return err
        if existing is None:
            # Creating a file through Edit is allowed when there is nothing to match against.
            content_to_write = replacement_content or args.get("content", "")
            if content_to_write and not target_content.strip():
                w_res = self.tool_write({"path": path_str, "content": content_to_write})
                if w_res.success:
                    return ToolExecutionResult(
                        success=True,
                        output=f"File '{path_str}' did not exist. Created new file with {len(content_to_write.splitlines())} lines.",
                        diff=f"+ (created {path_str})",
                    )
            return ToolExecutionResult(success=False, output="", error=f"File not found: '{path_str}'{self._suggest_paths(path_str)}")

        new_content, problem = apply_edit(existing, target_content, replacement_content, replace_all)
        if problem:
            return ToolExecutionResult(success=False, output="", error=f"{problem} (in '{path_str}')")
        return self._commit_edit(target, path_str, existing, new_content, f"Successfully edited '{path_str}'.")

    def tool_multiedit(self, args: dict[str, Any]) -> ToolExecutionResult:
        """Apply several edits to one file in order; all succeed or none are written."""
        path_str = args.get("path", "")
        edits = args.get("edits") or []
        if not isinstance(edits, list) or not edits:
            return ToolExecutionResult(success=False, output="", error="MultiEdit needs a non-empty 'edits' list")
        target, existing, err = self._load_for_edit(path_str)
        if err:
            return err
        if existing is None:
            return ToolExecutionResult(success=False, output="", error=f"File not found: '{path_str}'{self._suggest_paths(path_str)}")
        current = existing
        for i, e in enumerate(edits, 1):
            if not isinstance(e, dict) or "target_content" not in e or "replacement_content" not in e:
                return ToolExecutionResult(success=False, output="", error=f"Edit #{i} needs target_content and replacement_content")
            updated, problem = apply_edit(current, str(e["target_content"]), str(e["replacement_content"]), bool(e.get("replace_all")))
            if problem:
                return ToolExecutionResult(success=False, output="", error=f"Edit #{i} of {len(edits)} failed, nothing was written: {problem}")
            current = updated
        return self._commit_edit(target, path_str, existing, current, f"Applied {len(edits)} edits to '{path_str}'.")

    def tool_write(self, args: dict[str, Any]) -> ToolExecutionResult:
        path_str = args.get("path", "")
        content = args.get("content", "")

        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        self._ensure_checkpoint_for_file(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)
        self.state.record_file_write(str(target))
        notes = format_diagnostics(path_str, check_file(target, self.sandbox.primary_root))
        return ToolExecutionResult(success=True, output=f"Successfully wrote {len(content)} characters to '{path_str}'.{notes}")

    def tool_listdir(self, args: dict[str, Any]) -> ToolExecutionResult:
        path_str = args.get("path", ".")
        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        if not target.is_dir():
            return ToolExecutionResult(success=False, output="", error=f"Not a directory: '{path_str}'")

        items = []
        for p in sorted(target.iterdir()):
            if p.name.startswith(".") and p.name not in (".github", ".agents"):
                continue
            icon = "📁" if p.is_dir() else "📄"
            items.append(f"{icon} {p.name}")

        return ToolExecutionResult(success=True, output=f"Directory '{path_str}':\n" + "\n".join(items[:100]))

    def tool_glob(self, args: dict[str, Any]) -> ToolExecutionResult:
        pattern = args.get("pattern", "*")
        root_path = args.get("path", ".")
        try:
            target = self.sandbox.canonicalize_path(root_path)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        matches = []
        for p in target.glob(pattern):
            rel_parts = p.relative_to(self.sandbox.primary_root).parts if p.is_relative_to(self.sandbox.primary_root) else p.parts
            if not any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts):
                matches.append(str(p.relative_to(self.sandbox.primary_root)))

        return ToolExecutionResult(success=True, output=f"Glob matches for '{pattern}':\n" + "\n".join(matches[:100]))

    def tool_grep(self, args: dict[str, Any]) -> ToolExecutionResult:
        query = args.get("query", "")
        root_path = args.get("path", ".")
        glob = args.get("glob")
        try:
            target = self.sandbox.canonicalize_path(root_path)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))
        if not target.exists():
            return ToolExecutionResult(success=False, output="", error=f"Path not found: '{root_path}'")

        matches = self._grep_ripgrep(query, target, glob)
        if matches is None:
            matches = self._grep_python(query, target, glob)
        header = f"Grep '{query}' ({len(matches)} matches{', truncated' if len(matches) >= _GREP_LIMIT else ''}):"
        return ToolExecutionResult(success=True, output=header + "\n" + "\n".join(matches))

    def _grep_ripgrep(self, query: str, target: Path, glob: str | None) -> list[str] | None:
        import shutil
        import subprocess

        rg = shutil.which("rg")
        if not rg:
            return None
        cmd = [rg, "--line-number", "--no-heading", "--color=never", "--smart-case", "--max-columns=300",
               "--max-count=20", "-g", "!.git", "-g", "!*.lock"]
        for pat in _SENSITIVE_GLOBS:
            cmd += ["-g", f"!{pat}"]
        if glob:
            cmd += ["-g", glob]
        cmd += ["-e", query, str(target)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode not in (0, 1):
            return None
        root = str(self.sandbox.primary_root) + "/"
        out = []
        for line in proc.stdout.splitlines():
            out.append(line[len(root):] if line.startswith(root) else line)
            if len(out) >= _GREP_LIMIT:
                break
        return out

    def _grep_python(self, query: str, target: Path, glob: str | None) -> list[str]:
        import fnmatch
        import os

        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
        root = self.sandbox.primary_root
        files: list[Path]
        if target.is_file():
            files = [target]
        else:
            files = []
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS and d not in ("venv", ".venv")]
                for name in filenames:
                    if name.startswith(".") or (glob and not fnmatch.fnmatch(name, glob)):
                        continue
                    files.append(Path(dirpath) / name)
        matches: list[str] = []
        for f in files:
            if self.sandbox.is_sensitive_file(f):
                continue
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                with open(f, encoding="utf-8", errors="strict") as fh:
                    for i, line in enumerate(fh, 1):
                        if pattern.search(line):
                            rel = f.relative_to(root) if f.is_relative_to(root) else f
                            matches.append(f"{rel}:{i}: {line.strip()[:300]}")
                            if len(matches) >= _GREP_LIMIT:
                                return matches
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable
        return matches

    def tool_repomap(self, args: dict[str, Any]) -> ToolExecutionResult:
        from ijachi_router.context.repomap import build_repo_map

        path_str = args.get("path", ".")
        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))
        if not target.is_dir():
            return ToolExecutionResult(success=False, output="", error=f"Not a directory: '{path_str}'")
        return ToolExecutionResult(success=True, output=build_repo_map(self.sandbox.primary_root, target, max_chars=20_000))

    def tool_bash(self, args: dict[str, Any]) -> ToolExecutionResult:
        cmd = args.get("command", "")
        needs_network = bool(_NETWORK_CMD_RE.search(cmd))
        if args.get("run_in_background"):
            try:
                job_id = self.sandbox.start_background(cmd, needs_network=needs_network)
            except (RuntimeError, OSError) as e:
                return ToolExecutionResult(success=False, output="", error=str(e))
            return ToolExecutionResult(
                success=True,
                output=f"Started in background with id {job_id}. Use BashOutput {{\"id\": \"{job_id}\"}} to read its output "
                       f"and KillShell to stop it.",
            )
        timeout = int(args.get("timeout") or 120)
        code, stdout, stderr = self.sandbox.run_sandboxed_command(cmd, timeout_sec=max(5, min(timeout, 600)), needs_network=needs_network)

        out = f"Exit Code: {code}\n"
        if stdout:
            out += f"STDOUT:\n{stdout}\n"
        if stderr:
            out += f"STDERR:\n{stderr}\n"
        if code != 0 and self.sandbox.os_sandbox and ("Operation not permitted" in stderr or "Could not resolve host" in stderr):
            out += ("\nNote: commands run in an OS sandbox (writes limited to the workspace, network off except for "
                    "install/fetch commands). Work inside the workspace or ask the user to relax the sandbox.\n")
        return ToolExecutionResult(success=(code == 0), output=out, error=stderr if code != 0 else None)

    def tool_bashoutput(self, args: dict[str, Any]) -> ToolExecutionResult:
        from ijachi_router.agent.background import SHELLS
        from ijachi_router.agent.sandbox import redact_secrets

        job_id = str(args.get("id", ""))
        try:
            text, status, code = SHELLS.output(job_id)
        except KeyError:
            listing = ", ".join(j["id"] for j in SHELLS.list()) or "none"
            return ToolExecutionResult(success=False, output="", error=f"No background shell '{job_id}'. Known: {listing}")
        head = f"[{job_id}] status: {status}" + (f" (exit {code})" if code is not None else "")
        return ToolExecutionResult(success=True, output=f"{head}\n{redact_secrets(text) or '(no new output)'}")

    def tool_killshell(self, args: dict[str, Any]) -> ToolExecutionResult:
        from ijachi_router.agent.background import SHELLS

        job_id = str(args.get("id", ""))
        if not SHELLS.kill(job_id):
            return ToolExecutionResult(success=False, output="", error=f"No background shell '{job_id}'")
        return ToolExecutionResult(success=True, output=f"Stopped {job_id}.")

    def tool_webfetch(self, args: dict[str, Any]) -> ToolExecutionResult:
        from ijachi_router.agent.web import web_fetch

        ok, text = web_fetch(str(args.get("url", "")))
        return ToolExecutionResult(success=ok, output=text if ok else "", error=None if ok else text)

    def tool_websearch(self, args: dict[str, Any]) -> ToolExecutionResult:
        from ijachi_router.agent.web import web_search

        ok, text = web_search(str(args.get("query", "")))
        return ToolExecutionResult(success=ok, output=text if ok else "", error=None if ok else text)

    def tool_plan(self, args: dict[str, Any]) -> ToolExecutionResult:
        from ijachi_router.session.state import PlanStep

        goal = args.get("goal")
        if goal:
            self.state.active_goal = goal

        raw_steps = args.get("steps") or []
        steps = []
        for i, s in enumerate(raw_steps):
            if isinstance(s, dict):
                steps.append(PlanStep(id=s.get("id", i + 1), title=s.get("title", ""), status=s.get("status", "pending")))
            elif isinstance(s, str):
                steps.append(PlanStep(id=i + 1, title=s, status="pending"))

        if steps:
            self.state.plan_steps = steps

        return ToolExecutionResult(success=True, output="Plan updated successfully.")
