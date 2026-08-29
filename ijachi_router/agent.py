"""Agentic Workspace & File Editing Engine for ijachi-code.

Provides multi-step autonomous tool execution (read_file, write_file, edit_file,
list_dir, grep_search, run_command) powered by ijachi-llm-router's multi-provider engine.
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

console = Console()


# ---------------------------------------------------------------------------
# Workspace Tool Set
# ---------------------------------------------------------------------------

class WorkspaceTools:
    """Safely executes workspace operations on the local file system."""

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

    def edit_file(self, path: str, target_content: str, replacement_content: str, require_approval: bool = True) -> str:
        target = self._resolve_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist."
        try:
            existing = target.read_text(encoding="utf-8")
            if target_content not in existing:
                return f"Error: Target content string not found in '{path}'."
            if require_approval:
                console.print(f"\n[bold yellow]⚠️ Workspace File Edit Request[/bold yellow]")
                console.print(f"Target path: [cyan]{target}[/cyan]")
                console.print(f"[red]- Removing:[/red]\n{target_content[:300]}")
                console.print(f"[green]+ Adding:[/green]\n{replacement_content[:300]}")
                if not Confirm.ask("Do you want to apply this edit?", default=True):
                    return "Cancelled by user."

            new_content = existing.replace(target_content, replacement_content, 1)
            target.write_text(new_content, encoding="utf-8")
            return f"Successfully applied edit to '{path}'."
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


_SYSTEM_PROMPT = """You are ijachi-code, an autonomous agentic pair programmer.
You have access to the following workspace tools:
- read_file(path, start_line, end_line)
- write_file(path, content)
- edit_file(path, target_content, replacement_content)
- list_dir(path)
- grep_search(query, search_path)
- run_command(command)

To use a tool, respond with a JSON block in this exact format:
```json
{
  "thought": "Your reasoning steps here",
  "tool": "tool_name",
  "args": { ... }
}
```

If no further tool calls are required and your task is complete, respond with:
```json
{
  "thought": "Final summary of work done",
  "final_answer": "Complete final answer here"
}
```
"""


class AgenticRouter:
    """Autonomous agentic router that ties multi-provider routing to workspace tools."""

    def __init__(self, root_dir: Path | str | None = None, priority: str = "balanced", require_approval: bool = True):
        self.tools = WorkspaceTools(root_dir=root_dir)
        self.priority = priority
        self.require_approval = require_approval

    def run(self, task: str, max_steps: int = 10) -> AgentResult:
        conversation_history: list[dict[str, str]] = []
        steps: list[AgentStep] = []
        total_cost = 0.0

        current_prompt = f"{_SYSTEM_PROMPT}\n\nTask: {task}\n"

        for step_idx in range(1, max_steps + 1):
            console.print(f"[bold cyan]🤖 ijachi-code Step {step_idx}/{max_steps}[/bold cyan]")

            # Route prompt to optimal model
            res = route(prompt=current_prompt, priority=self.priority)
            total_cost += res.cost_usd

            response_text = res.text.strip()

            # Parse JSON tool call from LLM response
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
                return AgentResult(
                    final_text=final_text,
                    steps=steps,
                    total_cost_usd=total_cost,
                    completed=True,
                )

            thought = parsed.get("thought", "")
            tool_name = parsed.get("tool")
            args = parsed.get("args", {})

            console.print(f"[dim]Thought: {thought}[/dim]")
            console.print(f"[bold yellow]Tool Call: {tool_name}({args})[/bold yellow]")

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

        return AgentResult(
            final_text="Agentic loop reached maximum steps.",
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

