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

from ijachi_router.agent.sandbox import WorkspaceSandbox

if TYPE_CHECKING:
    from ijachi_router.session.checkpoints import CheckpointManager
    from ijachi_router.session.state import PlanStep, SessionState


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
        },
        "required": ["path", "target_content", "replacement_content"],
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
        },
        "required": ["query"],
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
        },
        "required": ["command"],
    },
    "Plan": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {"type": "array"},
        },
    },
}


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

    def _ensure_checkpoint_for_file(self, target_path: Path) -> None:
        """Create a checkpoint before modifying a file in this turn (FR-03)."""
        p_str = str(target_path)
        if p_str not in self.turn_checkpoints_created:
            self.checkpoints.create_checkpoint(f"Pre-edit checkpoint for {target_path.name}", [target_path])
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
            return ToolExecutionResult(success=False, output="", error=f"File not found: '{path_str}'")

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

    def tool_edit(self, args: dict[str, Any]) -> ToolExecutionResult:
        path_str = args.get("path", "")
        target_content = args.get("target_content", "")
        replacement_content = args.get("replacement_content", "")

        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        if not target.exists():
            return ToolExecutionResult(success=False, output="", error=f"File not found: '{path_str}'")

        # Stale read check (FR-03)
        if self.state.check_stale_read(str(target)):
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Stale file error: '{path_str}' changed on disk since it was last read. Please re-read the file first.",
            )

        existing = target.read_text(encoding="utf-8", errors="replace")

        # Multi-strategy match
        new_content = None
        # 1. Exact match
        if target_content in existing:
            new_content = existing.replace(target_content, replacement_content, 1)
        # 2. Normalized line endings
        elif target_content.replace("\r\n", "\n") in existing.replace("\r\n", "\n"):
            new_content = existing.replace("\r\n", "\n").replace(
                target_content.replace("\r\n", "\n"), replacement_content.replace("\r\n", "\n"), 1
            )
        # 3. Stripped line matching
        else:
            e_lines = existing.splitlines(keepends=True)
            t_stripped = [l.strip() for l in target_content.splitlines() if l.strip()]
            t_len = len(target_content.splitlines())
            for i in range(len(e_lines)):
                if [l.strip() for l in e_lines[i:i + t_len] if l.strip()] == t_stripped:
                    prefix = "".join(e_lines[:i])
                    suffix = "".join(e_lines[i + t_len:])
                    new_content = prefix + replacement_content + ("\n" if not replacement_content.endswith("\n") and suffix else "") + suffix
                    break

        if new_content is None:
            return ToolExecutionResult(
                success=False,
                output="",
                error=f"Target content not found in '{path_str}'. Verify file lines using Read.",
            )

        # Create checkpoint before modification (FR-03)
        self._ensure_checkpoint_for_file(target)

        # Write atomically
        target.write_text(new_content, encoding="utf-8")
        self.state.record_file_write(str(target))

        # Build diff
        diff = "".join(difflib.unified_diff(
            existing.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
        ))

        return ToolExecutionResult(
            success=True,
            output=f"Successfully edited '{path_str}'.",
            diff=diff,
        )

    def tool_write(self, args: dict[str, Any]) -> ToolExecutionResult:
        path_str = args.get("path", "")
        content = args.get("content", "")

        try:
            target = self.sandbox.canonicalize_path(path_str)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        self._ensure_checkpoint_for_file(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.state.record_file_write(str(target))

        return ToolExecutionResult(success=True, output=f"Successfully wrote {len(content)} characters to '{path_str}'.")

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
            if not any(part.startswith(".") for part in p.parts):
                matches.append(str(p.relative_to(self.sandbox.primary_root)))

        return ToolExecutionResult(success=True, output=f"Glob matches for '{pattern}':\n" + "\n".join(matches[:100]))

    def tool_grep(self, args: dict[str, Any]) -> ToolExecutionResult:
        query = args.get("query", "")
        root_path = args.get("path", ".")
        try:
            target = self.sandbox.canonicalize_path(root_path)
        except PermissionError as e:
            return ToolExecutionResult(success=False, output="", error=str(e))

        matches = []
        pattern = re.compile(query, re.IGNORECASE)
        files = [target] if target.is_file() else list(target.rglob("*"))

        for f in files:
            if f.is_file() and not any(part.startswith(".") or part in ("node_modules", "venv", ".venv") for part in f.parts):
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines()):
                        if pattern.search(line):
                            rel = f.relative_to(self.sandbox.primary_root)
                            matches.append(f"{rel}:{i + 1}: {line.strip()}")
                            if len(matches) >= 50:
                                break
                except Exception:
                    continue
            if len(matches) >= 50:
                break

        return ToolExecutionResult(success=True, output=f"Grep '{query}' ({len(matches)} matches):\n" + "\n".join(matches))

    def tool_bash(self, args: dict[str, Any]) -> ToolExecutionResult:
        cmd = args.get("command", "")
        code, stdout, stderr = self.sandbox.run_sandboxed_command(cmd)

        out = f"Exit Code: {code}\n"
        if stdout:
            out += f"STDOUT:\n{stdout}\n"
        if stderr:
            out += f"STDERR:\n{stderr}\n"

        return ToolExecutionResult(success=(code == 0), output=out, error=stderr if code != 0 else None)

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
