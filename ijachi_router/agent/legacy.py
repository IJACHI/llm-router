"""Legacy AgenticRouter, WorkspaceTools, and dual-scope memory functions for backward compatibility."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Confirm

from ijachi_router.core import route

console = Console()

_MEMORY_DIR = Path.home() / ".ijachi-llmr" / "memory"
_USER_MEMORY_FILE = _MEMORY_DIR / "user_preferences.txt"


def _get_memory_dir() -> Path:
    import ijachi_router.agent as agent_pkg
    return Path(getattr(agent_pkg, "_MEMORY_DIR", _MEMORY_DIR))


def _get_user_memory_file() -> Path:
    return _get_memory_dir() / "user_preferences.txt"


def _workspace_id(path: str | Path) -> str:
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]


def load_memory(workspace_path: str | Path, scope: str = "all") -> str | None:
    sections: list[str] = []
    user_file = _get_user_memory_file()
    if scope in ("all", "user") and user_file.exists():
        try:
            user_text = user_file.read_text(encoding="utf-8").strip()
            if user_text:
                sections.append(f"[Global Developer Preferences]\n{user_text}")
        except Exception:
            pass

    if scope in ("all", "project"):
        ws = Path(workspace_path).resolve()
        project_mem_file = ws / ".ijachi" / "memory.txt"
        wid = _workspace_id(ws)
        cached_mem_file = _get_memory_dir() / f"{wid}.txt"

        proj_text = ""
        if project_mem_file.exists():
            try:
                proj_text = project_mem_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        elif cached_mem_file.exists():
            try:
                proj_text = cached_mem_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        if proj_text:
            sections.append(f"[Project Workspace Memory]\n{proj_text}")

    return "\n\n".join(sections) if sections else None


def save_memory(workspace_path: str | Path, content: str, scope: str = "project") -> None:
    if not content.strip():
        return
    mem_dir = _get_memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)

    if scope == "user":
        user_file = _get_user_memory_file()
        try:
            existing = user_file.read_text(encoding="utf-8").strip() if user_file.exists() else ""
            entries = [e.strip() for e in existing.split("---") if e.strip()]
            entries.append(content.strip())
            entries = entries[-5:]
            user_file.write_text("\n---\n".join(entries), encoding="utf-8")
        except Exception:
            pass
        return

    ws = Path(workspace_path).resolve()
    local_dir = ws / ".ijachi"
    target_file = (local_dir / "memory.txt") if local_dir.exists() else (mem_dir / f"{_workspace_id(ws)}.txt")

    try:
        existing = target_file.read_text(encoding="utf-8").strip() if target_file.exists() else ""
        entries = [e.strip() for e in existing.split("---") if e.strip()]
        entries.append(content.strip())
        entries = entries[-5:]
        target_file.write_text("\n---\n".join(entries), encoding="utf-8")
    except Exception:
        pass


class WorkspaceTools:
    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()

    def _resolve_path(self, relative_or_abs: str) -> Path:
        p = Path(relative_or_abs)
        if not p.is_absolute():
            p = (self.root_dir / p).resolve()
        return p

    def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        target = self._resolve_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist."
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            s_idx = max(0, (start_line - 1)) if start_line is not None else 0
            e_idx = min(total_lines, end_line) if end_line is not None else total_lines
            selected = lines[s_idx:e_idx]
            numbered = [f"{i + s_idx + 1:4d} | {line}" for i, line in enumerate(selected)]
            return f"File: {path} (lines {s_idx + 1}-{e_idx} of {total_lines})\n" + "\n".join(numbered)
        except Exception as e:
            return f"Error reading file '{path}': {e}"

    def write_file(self, path: str, content: str, require_approval: bool = True) -> str:
        target = self._resolve_path(path)
        if require_approval:
            console.print(f"\n[bold yellow]⚠️ Workspace File Creation/Overwrite Request[/bold yellow]")
            console.print(f"Target path: [cyan]{target}[/cyan]")
            if not Confirm.ask("Do you want to proceed with writing to this file?", default=True):
                return "Cancelled by user."
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to '{path}'."
        except Exception as e:
            return f"Error writing file '{path}': {e}"

    @staticmethod
    def _apply_fuzzy_replace(existing: str, target: str, replacement: str) -> tuple[str | None, str]:
        if target in existing:
            return existing.replace(target, replacement, 1), "exact match"

        norm_existing = existing.replace("\r\n", "\n")
        norm_target = target.replace("\r\n", "\n")
        if norm_target in norm_existing:
            return norm_existing.replace(norm_target, replacement.replace("\r\n", "\n"), 1), "normalized line endings"

        existing_lines = existing.splitlines(keepends=True)
        target_lines_stripped = [l.strip() for l in target.splitlines() if l.strip()]
        if not target_lines_stripped:
            return None, ""

        raw_target_len = len(target.splitlines())
        match_start = -1
        match_end = -1

        for i in range(len(existing_lines)):
            slice_stripped = [l.strip() for l in existing_lines[i:i + raw_target_len] if l.strip()]
            if slice_stripped == target_lines_stripped:
                match_start = i
                match_end = i + raw_target_len
                break

        if match_start != -1:
            prefix = "".join(existing_lines[:match_start])
            suffix = "".join(existing_lines[match_end:])
            rep_text = replacement if (replacement.endswith("\n") or not suffix) else replacement + "\n"
            return prefix + rep_text + suffix, "indentation/whitespace tolerant"

        return None, ""

    def edit_file(self, path: str, target_content: str, replacement_content: str, require_approval: bool = True) -> str:
        target = self._resolve_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist."
        try:
            existing = target.read_text(encoding="utf-8")
            new_content, strategy = self._apply_fuzzy_replace(existing, target_content, replacement_content)
            if new_content is None:
                return (
                    f"Error: Target content string not found in '{path}'. "
                    f"Tried exact match, line ending normalization, and whitespace-tolerant matching."
                )

            if require_approval:
                console.print(f"\n[bold yellow]⚠️ Workspace File Edit Request[/bold yellow] [dim]({strategy})[/dim]")
                console.print(f"Target path: [cyan]{target}[/cyan]")
                console.print(f"[red]- Removing:[/red]\n{target_content[:300]}")
                console.print(f"[green]+ Adding:[/green]\n{replacement_content[:300]}")
                if not Confirm.ask("Do you want to apply this edit?", default=True):
                    return "Cancelled by user."

            target.write_text(new_content, encoding="utf-8")
            return f"Successfully applied edit to '{path}' ({strategy})."
        except Exception as e:
            return f"Error editing file '{path}': {e}"

    def list_dir(self, path: str = ".") -> str:
        target = self._resolve_path(path)
        if not target.exists() or not target.is_dir():
            return f"Error: Directory '{path}' does not exist."
        try:
            items = sorted(target.iterdir())
            formatted = []
            for item in items[:100]:
                prefix = "📁 " if item.is_dir() else "📄 "
                formatted.append(f"{prefix}{item.name}")
            return f"Directory listing for '{path}':\n" + "\n".join(formatted)
        except Exception as e:
            return f"Error listing directory '{path}': {e}"

    def grep_search(self, query: str, search_path: str = ".") -> str:
        target = self._resolve_path(search_path)
        results = []
        if not target.exists():
            return f"Error: Path '{search_path}' does not exist."
        try:
            pattern = re.compile(query, re.IGNORECASE)
            files = [target] if target.is_file() else list(target.rglob("*"))
            count = 0
            for f in files:
                if f.is_file() and not any(part.startswith(".") or part in {"node_modules", "venv", ".venv"} for part in f.parts):
                    try:
                        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
                        for i, line in enumerate(lines):
                            if pattern.search(line):
                                rel = f.relative_to(self.root_dir)
                                results.append(f"{rel}:{i + 1}: {line.strip()}")
                                count += 1
                                if count >= 50:
                                    break
                    except Exception:
                        continue
                if count >= 50:
                    break
            return f"Grep results for '{query}' ({len(results)} matches):\n" + "\n".join(results)
        except Exception as e:
            return f"Error running grep search: {e}"

    def run_command(self, command: str, require_approval: bool = True) -> str:
        if require_approval:
            console.print(f"\n[bold yellow]⚠️ Shell Execution Request[/bold yellow]")
            console.print(f"Command: [bold cyan]{command}[/bold cyan]")
            if not Confirm.ask("Do you want to run this command?", default=True):
                return "Command execution cancelled by user."
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            res = f"Exit Code: {proc.returncode}\n"
            if out:
                res += f"STDOUT:\n{out[:2000]}\n"
            if err:
                res += f"STDERR:\n{err[:2000]}\n"
            return res
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 60 seconds."
        except Exception as e:
            return f"Error running command: {e}"


@dataclass
class AgentStep:
    step_number: int
    thought: str
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_output: str
    model_used: str
    provider: str
    cost_usd: float


@dataclass
class AgentResult:
    final_text: str
    steps: list[AgentStep] = field(default_factory=list)
    total_cost_usd: float = 0.0
    completed: bool = True


_SYSTEM_PROMPT = """You are ijachi-code, an autonomous agentic pair programmer.
You have access to the following workspace tools:
- read_file(path, start_line, end_line)
- write_file(path, content)
- edit_file(path, target_content, replacement_content)
- list_dir(path)
- grep_search(query, search_path)
- run_command(command)
"""


class AgenticRouter:
    def __init__(
        self,
        root_dir: Path | str | None = None,
        priority: str = "balanced",
        require_approval: bool = True,
        workspace_context: str | None = None,
    ):
        self.tools = WorkspaceTools(root_dir=root_dir)
        self.priority = priority
        self.require_approval = require_approval
        self.workspace_context = workspace_context
        self._session_input_tokens: int = 0
        self._auto_compact_threshold: int = 60_000

    def _build_system_prompt(self) -> str:
        base = _SYSTEM_PROMPT
        if self.workspace_context:
            base = f"{base}\n\n{self.workspace_context}"
        return base

    @staticmethod
    def _micro_compact_turn(turn: str) -> str:
        lines = turn.splitlines()
        if "Tool Output (list_dir):" in turn and len(lines) > 8:
            header = lines[:5]
            count = len(lines) - 5
            return "\n".join(header) + f"\n... [{count} additional directory items collapsed to save context]"

        if "Tool Output (grep_search):" in turn and len(lines) > 8:
            header = lines[:5]
            count = len(lines) - 5
            return "\n".join(header) + f"\n... [{count} additional grep matches collapsed to save context]"

        if "Tool Output (read_file):" in turn and len(lines) > 40:
            head = lines[:15]
            tail = lines[-8:]
            collapsed = len(lines) - 23
            return "\n".join(head) + f"\n... [{collapsed} lines collapsed to save context] ...\n" + "\n".join(tail)

        return turn

    def run(self, task: str, max_steps: int = 10) -> AgentResult:
        import ijachi_router.agent as agent_pkg
        route_fn = getattr(agent_pkg, "route", route)

        steps: list[AgentStep] = []
        total_cost = 0.0
        current_prompt = f"Task: {task}\n"

        for step_idx in range(1, max_steps + 1):
            res = route_fn(prompt=current_prompt, priority=self.priority, _classify_as=task)
            self._session_input_tokens += res.input_tokens
            total_cost += res.cost_usd
            response_text = res.text.strip()

            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if not json_match:
                json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)

            parsed = None
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1))
                except Exception:
                    pass

            if not parsed or "final_answer" in parsed:
                final_text = parsed.get("final_answer", response_text) if parsed else response_text
                return AgentResult(final_text=final_text, steps=steps, total_cost_usd=total_cost, completed=True)

            thought = parsed.get("thought", "")
            tool_name = parsed.get("tool")
            args = parsed.get("args", {})

            tool_output = ""
            if tool_name == "read_file":
                tool_output = self.tools.read_file(path=args.get("path", ""), start_line=args.get("start_line"), end_line=args.get("end_line"))
            elif tool_name == "write_file":
                tool_output = self.tools.write_file(path=args.get("path", ""), content=args.get("content", ""), require_approval=self.require_approval)
            elif tool_name == "edit_file":
                tool_output = self.tools.edit_file(path=args.get("path", ""), target_content=args.get("target_content", ""), replacement_content=args.get("replacement_content", ""), require_approval=self.require_approval)
            elif tool_name == "list_dir":
                tool_output = self.tools.list_dir(path=args.get("path", "."))
            elif tool_name == "grep_search":
                tool_output = self.tools.grep_search(query=args.get("query", ""), search_path=args.get("search_path", "."))
            elif tool_name == "run_command":
                tool_output = self.tools.run_command(command=args.get("command", ""), require_approval=self.require_approval)
            else:
                tool_output = f"Unknown tool: {tool_name}"

            step_record = AgentStep(
                step_number=step_idx,
                thought=thought,
                tool_name=tool_name,
                tool_args=args,
                tool_output=tool_output,
                model_used=res.model,
                provider=res.provider,
                cost_usd=res.cost_usd,
            )
            steps.append(step_record)
            current_prompt += f"\nAssistant: {response_text}\nTool Output ({tool_name}):\n{tool_output}\nContinue task."

        return AgentResult(final_text="Agentic loop reached maximum steps.", steps=steps, total_cost_usd=total_cost, completed=False)

    def fix_tests(self, test_command: str = "pytest", max_retries: int = 3) -> AgentResult:
        for attempt in range(1, max_retries + 1):
            out = self.tools.run_command(test_command, require_approval=False)
            if "Exit Code: 0" in out:
                return AgentResult(final_text=f"Tests passed successfully on attempt {attempt}.", completed=True)
            res = self.run(f"Fix failing tests: {out}", max_steps=5)
            if res.completed and "Exit Code: 0" in self.tools.run_command(test_command, require_approval=False):
                return res
        return AgentResult(final_text=f"Failed to fix test suite after {max_retries} attempts.", completed=False)

    def git_commit(self, message: str | None = None) -> str:
        diff = self.tools.run_command("git diff", require_approval=False)
        if not diff.strip() or "Exit Code: 0" not in diff:
            return "No workspace changes to commit."
        if not message:
            message = "chore: automated agent commit"
        self.tools.run_command("git add .", require_approval=False)
        return self.tools.run_command(f'git commit -m "{message}"', require_approval=self.require_approval)
