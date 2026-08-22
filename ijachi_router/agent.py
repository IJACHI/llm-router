"""Agentic Workspace & File Editing Engine for ijachi-code.

Provides multi-step autonomous tool execution (read_file, write_file, edit_file,
list_dir, grep_search, run_command) powered by ijachi-llm-router's multi-provider engine.

New in this version
-------------------
- CodeFormatter integration: auto-formats written/edited files and enforces style
- SkillManager integration: auto-activates relevant skills based on the task
- TaskChecklist: real-time progress display during multi-step agent runs
- Enhanced permission dialogs with Ctrl+E LLM explanation support
- Desktop / terminal bell notification on task completion
- Message queue for input while the agent is busy
- Accessibility mode: plain labeled sequential output
"""

from __future__ import annotations

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
from ijachi_router.formatter import CodeFormatter
from ijachi_router.security import scan_and_fix, format_security_summary, scan
from ijachi_router.validator import validate

console = Console()


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def _notify(title: str, message: str) -> None:
    """Send a desktop notification and ring the terminal bell.

    Falls back gracefully if notification tools are unavailable.

    Args:
        title: Notification title (e.g. 'ijachi-code').
        message: Notification body text.
    """
    # Terminal bell
    print("\a", end="", flush=True)
    # macOS native notification
    if os.path.exists("/usr/bin/osascript"):
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                timeout=3, capture_output=True,
            )
        except Exception:
            pass
    # Linux libnotify
    elif os.path.exists("/usr/bin/notify-send"):
        try:
            subprocess.run(
                ["notify-send", title, message],
                timeout=3, capture_output=True,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Task Checklist
# ---------------------------------------------------------------------------

@dataclass
class ChecklistItem:
    """A single item in the agent task checklist."""
    label: str
    """Human-readable task description."""
    done: bool = False
    """True once the step is marked complete."""


class TaskChecklist:
    """Real-time task progress display shown during multi-step agent runs.

    In normal mode renders a Rich live panel; in accessibility mode prints
    plain labeled lines.

    Args:
        accessible: If True, use plain sequential output instead of Rich panels.
    """

    def __init__(self, accessible: bool = False) -> None:
        self.items: list[ChecklistItem] = []
        self.accessible = accessible

    def add(self, label: str) -> None:
        """Register a new checklist item.

        Args:
            label: Description of the step to track.
        """
        self.items.append(ChecklistItem(label=label))
        if self.accessible:
            print(f"task: [ ] {label}")

    def complete(self, index: int) -> None:
        """Mark item at *index* as done and re-render.

        Args:
            index: Zero-based index of the item to mark complete.
        """
        if 0 <= index < len(self.items):
            self.items[index].done = True
            if self.accessible:
                print(f"task: [x] {self.items[index].label}")
            else:
                self._render()

    def _render(self) -> None:
        """Print the current checklist state to the console."""
        lines = []
        for item in self.items:
            icon = "[green]✓[/green]" if item.done else "[yellow]○[/yellow]"
            lines.append(f"  {icon} {item.label}")
        console.print("[bold cyan]📋 Task Checklist[/bold cyan]")
        for line in lines:
            console.print(line)

    def render(self) -> None:
        """Publicly trigger a checklist render (used by Ctrl+T toggle)."""
        if self.accessible:
            for item in self.items:
                mark = "x" if item.done else " "
                print(f"task: [{mark}] {item.label}")
        else:
            self._render()


# ---------------------------------------------------------------------------
# Workspace Tool Set
# ---------------------------------------------------------------------------

class WorkspaceTools:
    """Safely executes workspace operations on the local file system.

    Integrates CodeFormatter to auto-format written/edited files and enforce
    configured style guide rules and comment requirements.

    Args:
        root_dir: Workspace root directory. Defaults to cwd.
        formatter: CodeFormatter instance. Created from config defaults if not provided.
        accessible: If True, use plain accessibility-mode output instead of Rich panels.
    """

    def __init__(
        self,
        root_dir: Path | str | None = None,
        formatter: CodeFormatter | None = None,
        accessible: bool = False,
    ):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.formatter = formatter or CodeFormatter()
        self.accessible = accessible
        self.auto_approve_task: bool = False

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
        """Write *content* to *path*, applying formatting and security scans.

        Pre-formats the content string, validates syntax, runs a security scan,
        prompts for approval if required, writes the file, then runs a post-write
        lint gate and format pass.

        Args:
            path: Relative or absolute file path.
            content: Full file content to write.
            require_approval: If True, prompt the user before writing.

        Returns:
            Status message describing the outcome.
        """
        target = self._resolve_path(path)
        ext = target.suffix.lower()

        # Pre-format content string before validation
        content = self.formatter.format_content(content, filename=str(target))

        # Zero-regression validation gate
        val = validate(content, filename=str(target))
        if not val.valid:
            return f"Write blocked - validation errors:\n{val.summary()}"
        if val.warnings:
            console.print(f"[yellow]{val.summary()}[/yellow]")

        # Security scan & auto-remediate
        content, sec_issues = scan_and_fix(content)
        report = scan(content)
        if not report.is_safe:
            console.print(f"[bold red]{format_security_summary(report)}[/bold red]")

        if require_approval and not self.auto_approve_task:
            if self.accessible:
                print(f"permission_required: Write to {target}? [y/n/a=all]: ")
                answer = input().strip().lower()
                if answer in ("a", "all"):
                    self.auto_approve_task = True
                elif answer not in ("y", ""):
                    return "Cancelled by user."
            else:
                console.print(f"\n[bold yellow]⚠️ Workspace File Creation/Overwrite Request[/bold yellow]")
                console.print(f"Target path: [cyan]{target}[/cyan]")
                console.print("[dim]Options: [bold]y[/bold]=proceed  [bold]a[/bold]=approve all in task  [bold]n[/bold]=cancel[/dim]")
                try:
                    choice = input("Choice [y/n/a]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    choice = "n"
                if choice in ("a", "all"):
                    self.auto_approve_task = True
                elif choice not in ("y", ""):
                    return "Cancelled by user."
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            # Post-write: format on disk + lint gate
            fmt_result = self.formatter.format(target)
            status = f"Successfully wrote {len(content)} characters to '{path}'."
            if fmt_result.changed:
                status += f" (auto-formatted with {fmt_result.formatter_used})"
            if fmt_result.lint_warnings:
                warnings_str = "\n  ".join(fmt_result.lint_warnings[:5])
                status += f"\n  Lint warnings:\n  {warnings_str}"
            return status
        except Exception as e:
            return f"Error writing file '{path}': {e}"

    def edit_file(self, path: str, target_content: str, replacement_content: str, require_approval: bool = True) -> str:
        """Apply a targeted edit to *path*, formatting and scanning the result.

        Finds *target_content* in the file, replaces it with *replacement_content*,
        validates the resulting file, runs a security scan, prompts for approval,
        writes it, then runs a post-write lint gate.

        Args:
            path: Relative or absolute file path.
            target_content: Exact string to search for in the file.
            replacement_content: Replacement string.
            require_approval: If True, show a diff and prompt before writing.

        Returns:
            Status message describing the outcome.
        """
        target = self._resolve_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist."
        try:
            existing = target.read_text(encoding="utf-8")
            if target_content not in existing:
                return f"Error: Target content string not found in '{path}'."

            new_content = existing.replace(target_content, replacement_content, 1)

            # Zero-regression validation gate on the full resulting file
            val = validate(new_content, filename=str(target))
            if not val.valid:
                return f"Edit blocked - would cause syntax errors:\n{val.summary()}"
            if val.warnings:
                console.print(f"[yellow]{val.summary()}[/yellow]")

            # Security scan the replacement content
            replacement_content, _ = scan_and_fix(replacement_content)
            new_content = existing.replace(target_content, replacement_content, 1)
            report = scan(new_content)
            if not report.is_safe:
                console.print(f"[bold red]{format_security_summary(report)}[/bold red]")

            if require_approval and not self.auto_approve_task:
                if self.accessible:
                    print(f"permission_required: Edit {target}? [y/n/a=all/e=explain]: ")
                    answer = input().strip().lower()
                    if answer in ("a", "all"):
                        self.auto_approve_task = True
                    elif answer not in ("y", ""):
                        return "Cancelled by user."
                else:
                    console.print(f"\n[bold yellow]⚠️ Workspace File Edit Request[/bold yellow]")
                    console.print(f"Target path: [cyan]{target}[/cyan]")
                    console.print(f"[red]- Removing:[/red]\n{target_content[:300]}")
                    console.print(f"[green]+ Adding:[/green]\n{replacement_content[:300]}")
                    console.print("[dim]Options: [bold]y[/bold]=apply  [bold]a[/bold]=approve all  [bold]n[/bold]=cancel  [bold]e[/bold]=explain[/dim]")
                    try:
                        choice = input("Choice [y/n/a/e]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        choice = "n"
                    if choice == "e":
                        self._explain_edit(target_content, replacement_content)
                        try:
                            choice = input("Apply after explanation? [y/n/a]: ").strip().lower()
                        except (KeyboardInterrupt, EOFError):
                            choice = "n"
                    if choice in ("a", "all"):
                        self.auto_approve_task = True
                    elif choice not in ("y", ""):
                        return "Cancelled by user."

            target.write_text(new_content, encoding="utf-8")

            # Post-write: format on disk + lint gate
            fmt_result = self.formatter.format(target)
            status = f"Successfully applied edit to '{path}'."
            if fmt_result.changed:
                status += f" (auto-formatted with {fmt_result.formatter_used})"
            if fmt_result.lint_warnings:
                warnings_str = "\n  ".join(fmt_result.lint_warnings[:5])
                status += f"\n  Lint warnings:\n  {warnings_str}"
            return status
        except Exception as e:
            return f"Error editing file '{path}': {e}"

    def _explain_edit(self, target_content: str, replacement_content: str) -> None:
        """Use the LLM to explain what a proposed edit does and why."""
        prompt = (
            "Explain in 2-3 sentences what the following code change does and "
            "why it might be necessary:\n\n"
            f"REMOVING:\n```\n{target_content[:500]}\n```\n\n"
            f"ADDING:\n```\n{replacement_content[:500]}\n```"
        )
        try:
            res = route(prompt=prompt, priority="speed")
            console.print(f"\n[bold cyan]🔍 Edit Explanation:[/bold cyan]\n{res.text}\n")
        except Exception as exc:
            console.print(f"[yellow]Could not generate explanation: {exc}[/yellow]")

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
        """Run *command* as a shell command, with optional approval prompt."""
        if require_approval and not self.auto_approve_task:
            if self.accessible:
                print(f"permission_required: Run command '{command}'? [y/n/a=all/e=explain]: ")
                try:
                    answer = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    answer = "n"
                if answer in ("a", "all"):
                    self.auto_approve_task = True
                elif answer not in ("y", ""):
                    return "Command execution cancelled by user."
            else:
                console.print(f"\n[bold yellow]⚠️ Shell Execution Request[/bold yellow]")
                console.print(f"Command: [bold cyan]{command}[/bold cyan]")
                console.print("[dim]Options: [bold]y[/bold]=run  [bold]a[/bold]=approve all in task  [bold]n[/bold]=cancel  [bold]e[/bold]=explain[/dim]")
                try:
                    choice = input("Choice [y/n/a/e]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    choice = "n"
                if choice == "e":
                    self._explain_command(command)
                    try:
                        choice = input("Run after explanation? [y/n/a]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        choice = "n"
                if choice in ("a", "all"):
                    self.auto_approve_task = True
                elif choice not in ("y", ""):
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

    def _explain_command(self, command: str) -> None:
        """Use the LLM to explain what a shell command does."""
        prompt = (
            f"Explain in plain English what this shell command does, what it modifies, "
            f"and any potential risks:\n\n```sh\n{command}\n```"
        )
        try:
            res = route(prompt=prompt, priority="speed")
            console.print(f"\n[bold cyan]🔍 Command Explanation:[/bold cyan]\n{res.text}\n")
        except Exception as exc:
            console.print(f"[yellow]Could not generate explanation: {exc}[/yellow]")

    def git_checkpoint(self) -> str:
        """Create a temporary Git stash checkpoint before multi-file edits."""
        return self.run_command("git stash push -u -m 'ijachi-code safety checkpoint'", require_approval=False)

    def git_commit(self, message: str | None = None) -> str:
        """Generate a conventional commit message from git diff and commit."""
        status = self.run_command("git status --porcelain", require_approval=False)
        if not status.strip() or "Exit Code: 0" not in status:
            return "No workspace changes to commit."

        if not message:
            diff = self.run_command("git diff", require_approval=False)
            prompt = (
                f"Generate a single-line Conventional Commit message (e.g. feat(scope): message) "
                f"for the following git diff:\n\n{diff[:3000]}"
            )
            res = route(prompt=prompt, priority="speed")
            message = res.text.strip().splitlines()[0].replace('"', '')

        self.run_command("git add .", require_approval=False)
        return self.run_command(f'git commit -m "{message}"', require_approval=self.require_approval)


# ---------------------------------------------------------------------------
# JSON Tool Call Extraction & Repair Helpers
# ---------------------------------------------------------------------------

def _extract_balanced_json(text: str) -> str | None:
    """Extract the first bracket-balanced JSON substring from text."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _try_parse_json(candidate: str) -> dict | None:
    """Attempt JSON parsing with multi-strategy repair fallbacks."""
    if not candidate or not candidate.strip():
        return None
    candidate = candidate.strip()

    # Strategy 1: standard parse
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Strategy 2: strict=False (allows unescaped control chars)
    try:
        data = json.loads(candidate, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Strategy 3: repair raw newlines in string properties
    try:
        repaired = re.sub(
            r'("(?:[^"\\]|\\.)*")',
            lambda m: m.group(0).replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"),
            candidate,
        )
        data = json.loads(repaired, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return None


def _extract_tool_call(response_text: str) -> dict | None:
    """Extract tool call or final_answer dictionary from LLM response."""
    text = response_text.strip()
    if not text:
        return None

    # 1. Look for ```json ... ``` blocks
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE):
        block = match.group(1).strip()
        data = _try_parse_json(block)
        if data and ("tool" in data or "final_answer" in data):
            return data
        balanced = _extract_balanced_json(block)
        if balanced:
            data = _try_parse_json(balanced)
            if data and ("tool" in data or "final_answer" in data):
                return data

    # 2. Look for top-level balanced JSON in text
    balanced = _extract_balanced_json(text)
    if balanced:
        data = _try_parse_json(balanced)
        if data and ("tool" in data or "final_answer" in data):
            return data

    # 3. Direct parse of entire response text
    data = _try_parse_json(text)
    if data and ("tool" in data or "final_answer" in data):
        return data

    return None


# ---------------------------------------------------------------------------
# Agentic Execution Loop
# ---------------------------------------------------------------------------

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


_STYLE_INSTRUCTION = """
## Code Generation Requirements
- Write clean, idiomatic, production-ready code.
- Every module, class, and public function MUST have a docstring/JSDoc comment.
- Add inline comments for non-obvious logic.
- Use descriptive variable and function names — no cryptic abbreviations.
- Include type annotations for all function signatures.
- Handle errors explicitly; never silently swallow exceptions.
- Extract magic numbers and string literals into named constants.
"""

_SYSTEM_PROMPT = """You are ijachi-code, an autonomous agentic pair programmer running directly in the user's workspace.

## CRITICAL EXECUTION DIRECTIVES:
1. AUTONOMOUS FILE CREATION & SCAFFOLDING:
   When the user asks you to build, create, scaffold, write, edit, or test code:
   - DO NOT output code blocks in conversational markdown.
   - DO NOT tell the user to "create these files manually" or "clone a repository".
   - You MUST immediately issue `write_file`, `edit_file`, or `run_command` tool calls to build the files on disk directly.
   - Create one file at a time using `write_file` until the full project is completely built and functional.

2. WORKSPACE AWARENESS ON STATUS QUERIES:
   When the user asks status questions (e.g. "are you done?", "what is the status?", "how do I see/run the app?"):
   - Inspect the workspace or reference previous context before answering.
   - If files exist (e.g. app.py), provide concrete instructions on how to run them (e.g. `python app.py`).

3. TOOL CALL FORMAT:
To execute a tool, your entire response MUST be a single valid JSON block in this exact schema:
```json
{
  "thought": "Clear explanation of what you are doing and which file you are writing",
  "tool": "tool_name",
  "args": { ... }
}
```

Available tools:
- read_file(path: str, start_line: int | None, end_line: int | None)
- write_file(path: str, content: str)
- edit_file(path: str, target_content: str, replacement_content: str)
- list_dir(path: str)
- grep_search(query: str, search_path: str)
- run_command(command: str)

4. COMPLETION:
Only when all required files are written and the task is 100% complete, respond with:
```json
{
  "thought": "Summary of everything created and verified",
  "final_answer": "Complete summary and instructions for the user"
}
```
""" + _STYLE_INSTRUCTION


class AgenticRouter:
    """Autonomous agentic router that ties multi-provider routing to workspace tools.

    Integrates skill auto-activation, code formatting, task checklist display,
    and desktop notifications into the agent execution loop.

    Args:
        root_dir: Workspace root. Defaults to cwd.
        priority: Routing priority ('cost', 'speed', 'quality', 'balanced').
        require_approval: If True, prompt before file writes, edits, and shell commands.
        style_guide: Code style guide to enforce (e.g. 'pep8', 'prettier').
        auto_format: If True, auto-format files after write/edit tool calls.
        require_comments: If True, inject missing docstrings/JSDoc headers.
        accessible: If True, use plain sequential labeled output (screen-reader mode).
    """

    def __init__(
        self,
        root_dir: Path | str | None = None,
        priority: str = "balanced",
        require_approval: bool = True,
        style_guide: str = "pep8",
        auto_format: bool = True,
        require_comments: bool = True,
        accessible: bool = False,
        force_model: str | None = None,
        context_manager: Any | None = None,
    ):
        self.formatter = CodeFormatter(
            style_guide=style_guide,
            auto_format=auto_format,
            require_comments=require_comments,
        )
        self.tools = WorkspaceTools(
            root_dir=root_dir,
            formatter=self.formatter,
            accessible=accessible,
        )
        self.priority = priority
        self.force_model = force_model
        self.require_approval = require_approval
        self.accessible = accessible
        self.checklist = TaskChecklist(accessible=accessible)

        # Multi-layer Context Memory Manager (L1 Global, L2 Session, L3 Task)
        if context_manager is not None:
            self.ctx = context_manager
        else:
            from ijachi_router.context_manager import ContextManager
            self.ctx = ContextManager(root_dir=self.tools.root_dir)

        # Load and prepare skill manager
        from ijachi_router.skill_manager import SkillManager
        self._skill_manager = SkillManager(workspace_root=self.tools.root_dir)

    def set_model(self, model_id: str | None) -> None:
        """Switch or pin a specific model dynamically."""
        if hasattr(self, "ctx"):
            self.ctx.record_model_switch(self.force_model or "auto", model_id or "auto")
        self.force_model = model_id

    def set_priority(self, priority: str) -> None:
        """Switch routing priority dynamically."""
        self.priority = priority
        self.force_model = None

    def run(self, task: str, max_steps: int = 10) -> AgentResult:
        """Execute *task* autonomously using the workspace tool set.

        Auto-activates relevant skills from SkillManager and prepends their
        instructions to the system prompt. Displays a task checklist and
        notifies on completion.

        Args:
            task: The user's task description or instruction.
            max_steps: Maximum number of LLM→tool iterations before stopping.

        Returns:
            :class:`AgentResult` with the final answer, step log, and cost.
        """
        conversation_history: list[dict[str, str]] = []
        steps: list[AgentStep] = []
        total_cost = 0.0

        # Reset task-level approval cache for each new user run
        self.tools.auto_approve_task = False

        # Auto-activate skills matching the task
        active_skills = self._skill_manager.get_active_skills(task)
        skill_prompt = self._skill_manager.build_skill_prompt(active_skills)
        if active_skills and not self.accessible:
            skill_names = ", ".join(s.name for s in active_skills)
            console.print(f"[dim cyan]⚡ Activated skills: {skill_names}[/dim cyan]")

        # Build full system prompt: base + style guide + active skills
        style_block = self.formatter.get_style_prompt()
        full_system_prompt = _SYSTEM_PROMPT + style_block + skill_prompt

        # Inject multi-layer context block (L1 Global + L2 Session + L3 Task History)
        context_block = self.ctx.build_context_block(task)
        if context_block:
            current_prompt = f"{full_system_prompt}\n\n{context_block}\n\nTask: {task}\n"
        else:
            current_prompt = f"{full_system_prompt}\n\nTask: {task}\n"

        for step_idx in range(1, max_steps + 1):
            if self.accessible:
                print(f"ijachi: [step {step_idx}/{max_steps}] thinking...")
            else:
                console.print(f"[bold cyan]🤖 ijachi-code Step {step_idx}/{max_steps}[/bold cyan]")

            # Route: classify only the *task* text for model selection,
            # but send the full conversation context as the actual prompt.
            res = route(
                prompt=current_prompt,
                priority=self.priority,
                force_model=self.force_model,
                _classify_as=task,
            )
            total_cost += res.cost_usd

            response_text = res.text.strip()

            # Parse JSON tool call using robust multi-layer extractor
            parsed = _extract_tool_call(response_text)

            # If the response looks like an attempted tool call but failed extraction, prompt retry
            if parsed is None and any(k in response_text for k in ('"tool"', '"args"', 'write_file', 'edit_file', 'read_file', 'list_dir')):
                current_prompt += (
                    f"\nAssistant: {response_text}\n"
                    f"System Error: Invalid JSON syntax in tool call. Respond ONLY with a single valid JSON block matching:\n"
                    f"```json\n{{\"thought\": \"reasoning\", \"tool\": \"tool_name\", \"args\": {{...}}}}\n```"
                )
                continue

            if not parsed or "final_answer" in parsed:
                final_text = parsed.get("final_answer", response_text) if parsed else response_text
                # Notify on completion
                _notify("ijachi-code", "Task complete ✓")
                # Record in Multi-Layer Context Memory
                if hasattr(self, "ctx"):
                    self.ctx.record_task(
                        task=task,
                        result_text=final_text,
                        model=res.model if res else "auto",
                        cost_usd=total_cost,
                    )
                return AgentResult(
                    final_text=final_text,
                    steps=steps,
                    total_cost_usd=total_cost,
                    completed=True,
                )

            thought = parsed.get("thought", "")
            tool_name = parsed.get("tool")
            args = parsed.get("args", {})

            if self.accessible:
                print(f"ijachi: {thought}")
                print(f"tool: {tool_name}({list(args.keys())})")
            else:
                if thought:
                    console.print(f"[dim]Thought: {thought}[/dim]")
                # Format friendly summary
                arg_parts = []
                for k, v in (args or {}).items():
                    if isinstance(v, str) and len(v) > 60:
                        lines = v.count("\n") + 1
                        arg_parts.append(f"{k}=... ({lines} lines)")
                    else:
                        arg_parts.append(f"{k}={v!r}")
                tool_display = f"🛠  {tool_name}({', '.join(arg_parts)})"
                console.print(f"[bold yellow]{tool_display}[/bold yellow]")

            tool_output = ""
            if tool_name == "read_file":
                tool_output = self.tools.read_file(
                    path=args.get("path", ""),
                    start_line=args.get("start_line"),
                    end_line=args.get("end_line"),
                )
            elif tool_name == "write_file":
                tool_output = self.tools.write_file(
                    path=args.get("path", ""),
                    content=args.get("content", ""),
                    require_approval=self.require_approval,
                )
            elif tool_name == "edit_file":
                tool_output = self.tools.edit_file(
                    path=args.get("path", ""),
                    target_content=args.get("target_content", ""),
                    replacement_content=args.get("replacement_content", ""),
                    require_approval=self.require_approval,
                )
            elif tool_name == "list_dir":
                tool_output = self.tools.list_dir(path=args.get("path", "."))
            elif tool_name == "grep_search":
                tool_output = self.tools.grep_search(
                    query=args.get("query", ""),
                    search_path=args.get("search_path", "."),
                )
            elif tool_name == "run_command":
                tool_output = self.tools.run_command(
                    command=args.get("command", ""),
                    require_approval=self.require_approval,
                )
            else:
                tool_output = f"Unknown tool: {tool_name}"

            if self.accessible:
                if "error" in tool_output.lower() or "Exit Code: 1" in tool_output:
                    print(f"tool_error: {tool_name} → {tool_output[:200]}")
                else:
                    print(f"tool: {tool_name} → done")

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

        final_exit_text = "Agentic loop reached maximum steps."
        if hasattr(self, "ctx"):
            self.ctx.record_task(
                task=task,
                result_text=final_exit_text,
                model=res.model if res else "auto",
                cost_usd=total_cost,
            )
        return AgentResult(
            final_text=final_exit_text,
            steps=steps,
            total_cost_usd=total_cost,
            completed=False,
        )

    def fix_tests(self, test_command: str = "pytest", max_retries: int = 3) -> AgentResult:
        """Automated test repair loop: run test suite, capture failures, route fixes, and re-run until 100% pass."""
        console.print(f"[bold cyan]🧪 Starting Auto-Fixing Test Repair Loop: '{test_command}'[/bold cyan]")
        for attempt in range(1, max_retries + 1):
            console.print(f"\n[bold yellow]Attempt {attempt}/{max_retries} running '{test_command}'...[/bold yellow]")
            out = self.tools.run_command(test_command, require_approval=False)
            if "Exit Code: 0" in out:
                console.print("[bold green]✅ All tests passed 100%![/bold green]")
                return AgentResult(final_text=f"Tests passed successfully on attempt {attempt}.", completed=True)

            console.print(f"[bold red]❌ Test suite failed. Routing stack trace to reasoning model for repairs...[/bold red]")
            task_prompt = (
                f"The test command '{test_command}' failed with output:\n\n{out[:4000]}\n\n"
                f"Inspect workspace files, locate the failing code, apply the required fix using edit_file/write_file, and verify."
            )
            res = self.run(task_prompt, max_steps=5)
            if res.completed and "Exit Code: 0" in self.tools.run_command(test_command, require_approval=False):
                console.print("[bold green]✅ All tests passed after automated repairs![/bold green]")
                return res

        return AgentResult(final_text=f"Failed to fix test suite after {max_retries} attempts.", completed=False)

