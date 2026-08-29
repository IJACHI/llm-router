"""Rich Interactive REPL for ijachi-code.

Replaces the raw click.prompt loop with a feature-rich terminal session:
- Slash command dispatch (/clear /plan /auto /status /providers /memory /help)
- Live cost meter and model badge in status bar
- Git branch + dirty file count in status bar
- Rich bordered response panels with syntax highlighting
- Session cost accumulation
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

# ---------------------------------------------------------------------------
# Slash command registry
# ---------------------------------------------------------------------------

@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable[["RichREPL", str], bool]  # returns True to exit


_SLASH_COMMANDS: dict[str, SlashCommand] = {}


def _register(name: str, description: str):
    def decorator(fn):
        _SLASH_COMMANDS[name] = SlashCommand(name=name, description=description, handler=fn)
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _git_status_line() -> str:
    """Return a compact git status string: branch + dirty count."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        dirty_count = len([l for l in dirty.splitlines() if l.strip()])
        dirty_indicator = f" [bold red]({dirty_count} modified)[/bold red]" if dirty_count else ""
        return f"[dim cyan]⎇ {branch}{dirty_indicator}[/dim cyan]"
    except Exception:
        return ""


def _render_response(text: str, model_used: str, cost_usd: float, step: int) -> None:
    """Render a rich-formatted response panel."""
    header = Text()
    header.append("🤖 ", style="bold")
    header.append(model_used, style="bold cyan")
    header.append(f"  💰 ${cost_usd:.4f}", style="dim green")

    # Try to render as Markdown for rich formatting
    try:
        content = Markdown(text)
    except Exception:
        content = Text(text)

    console.print(Panel(
        content,
        title=header,
        border_style="bright_blue",
        padding=(0, 1),
    ))


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------

@_register("/help", "Show all available slash commands")
def _cmd_help(repl: "RichREPL", args: str) -> bool:
    table = Table(title="📖 IJACHI CODE Commands", border_style="bright_blue", show_header=True)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description", style="white")
    for cmd in _SLASH_COMMANDS.values():
        table.add_row(cmd.name, cmd.description)
    table.add_row("exit / quit / q", "End the session")
    console.print(table)
    return False


@_register("/clear", "Clear conversation context and start fresh")
def _cmd_clear(repl: "RichREPL", args: str) -> bool:
    repl.history.clear()
    repl.session_cost = 0.0
    console.print("[bold green]✓ Context cleared.[/bold green] Session cost reset to $0.00")
    return False


@_register("/status", "Show current model, provider, and session cost")
def _cmd_status(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.health import check_providers_quick
    from ijachi_router.config import load_config
    cfg = load_config()
    check_providers_quick(cfg)
    console.print(f"[bold cyan]💰 Session cost:[/bold cyan] ${repl.session_cost:.4f}")
    console.print(f"[bold cyan]💬 Messages in context:[/bold cyan] {len(repl.history)}")
    console.print(_git_status_line())
    return False


@_register("/providers", "Show active providers and their health status")
def _cmd_providers(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.health import check_providers_quick, render_provider_card
    from ijachi_router.config import load_config
    cfg = load_config()
    statuses = check_providers_quick(cfg)
    render_provider_card(statuses)
    return False


@_register("/auto", "Toggle auto-approval for file operations (no more confirmation prompts)")
def _cmd_auto(repl: "RichREPL", args: str) -> bool:
    repl.auto_approve = not repl.auto_approve
    state = "[bold green]ON[/bold green]" if repl.auto_approve else "[bold red]OFF[/bold red]"
    console.print(f"[bold cyan]Auto-approval:[/bold cyan] {state}")
    return False


@_register("/plan", "Enable plan-first mode for the next task (shows plan before executing)")
def _cmd_plan(repl: "RichREPL", args: str) -> bool:
    repl.plan_mode = not repl.plan_mode
    state = "[bold green]ON[/bold green]" if repl.plan_mode else "[bold yellow]OFF[/bold yellow]"
    console.print(f"[bold cyan]Plan-first mode:[/bold cyan] {state}")
    return False


@_register("/memory", "Show or clear persistent session memory")
def _cmd_memory(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.agent import load_memory, save_memory
    workspace_id = str(Path.cwd())
    mem = load_memory(workspace_id)
    if args.strip() == "clear":
        save_memory(workspace_id, "")
        console.print("[bold green]✓ Memory cleared.[/bold green]")
    elif mem:
        console.print(Panel(
            mem,
            title="[bold cyan]📝 Session Memory[/bold cyan]",
            border_style="cyan",
        ))
    else:
        console.print("[dim]No memory for this workspace yet.[/dim]")
    return False


@_register("/compact", "Manually compress conversation history to save context")
def _cmd_compact(repl: "RichREPL", args: str) -> bool:
    if not repl.history:
        console.print("[dim]Nothing to compact.[/dim]")
        return False
    console.print("[bold cyan]🔄 Compacting context...[/bold cyan]")
    from ijachi_router.core import route
    full = "\n".join(m.get("content", "") for m in repl.history[-20:])
    res = route(
        f"Summarize this conversation in 3-5 bullet points preserving key decisions and code changes:\n\n{full[:6000]}",
        priority="cost",
    )
    summary = res.text.strip()
    repl.history.clear()
    repl.history.append({"role": "system", "content": f"[Compacted context]\n{summary}"})
    console.print(f"[bold green]✓ Compacted {len(full)} chars → {len(summary)} chars summary[/bold green]")
    return False


# ---------------------------------------------------------------------------
# Main REPL class
# ---------------------------------------------------------------------------

@dataclass
class RichREPL:
    """Rich interactive REPL for ijachi-code chat sessions."""

    priority: str = "balanced"
    plan_mode: bool = False
    auto_approve: bool = False
    history: list[dict] = field(default_factory=list)
    session_cost: float = 0.0

    def _render_status_bar(self) -> None:
        """Print a compact status line before the prompt."""
        git_line = _git_status_line()
        cost_str = f"[bold green]💰 ${self.session_cost:.4f}[/bold green]"
        auto_str = "[bold green]AUTO[/bold green]" if self.auto_approve else "[dim]manual[/dim]"
        plan_str = "[bold magenta]PLAN[/bold magenta]" if self.plan_mode else ""
        parts = [p for p in [git_line, cost_str, auto_str, plan_str] if p]
        console.print("  ".join(parts), highlight=False)

    def _handle_slash(self, text: str) -> bool | None:
        """Dispatch slash commands. Returns True to exit, False to continue, None if not a slash cmd."""
        parts = text.strip().split(None, 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        if cmd_name in _SLASH_COMMANDS:
            return _SLASH_COMMANDS[cmd_name].handler(self, args)
        console.print(f"[bold red]Unknown command:[/bold red] {cmd_name}. Type [bold cyan]/help[/bold cyan] for all commands.")
        return False

    def _run_agentic(self, task: str) -> None:
        """Route task through the agentic engine with optional plan-first mode."""
        from ijachi_router.agent import AgenticRouter
        from ijachi_router.workspace_context import load_workspace_context

        ctx = load_workspace_context(Path.cwd())
        agent = AgenticRouter(
            require_approval=not self.auto_approve,
            priority=self.priority,
            workspace_context=ctx,
        )

        if self.plan_mode:
            from ijachi_router.planner import generate_plan, render_plan, await_plan_approval
            console.print("[bold magenta]🧠 Generating execution plan...[/bold magenta]")
            plan = generate_plan(task, agent)
            render_plan(plan)
            if not await_plan_approval():
                console.print("[dim]Plan rejected. Task cancelled.[/dim]")
                return

        result = agent.run(task)
        self.session_cost += result.total_cost_usd
        _render_response(
            result.final_text,
            model_used=f"ijachi/{self.priority}",
            cost_usd=result.total_cost_usd,
            step=len(result.steps),
        )

        # Save to memory
        from ijachi_router.agent import save_memory
        workspace_id = str(Path.cwd())
        save_memory(workspace_id, f"Task: {task[:200]}\nResult: {result.final_text[:500]}")

    def _run_simple(self, prompt: str) -> None:
        """Route a simple (non-agentic) prompt."""
        from ijachi_router.core import route
        res = route(prompt, priority=self.priority)
        self.session_cost += res.cost_usd
        _render_response(res.text, model_used=res.model_used, cost_usd=res.cost_usd, step=1)

    def _is_agentic_task(self, text: str) -> bool:
        """Heuristic: does this look like a workspace/file task?"""
        agentic_keywords = [
            "build", "create", "write", "edit", "fix", "refactor", "implement",
            "add", "remove", "delete", "read", "open", "run", "test", "deploy",
            "install", "scaffold", "generate", "update", "modify",
        ]
        lower = text.lower()
        return any(kw in lower for kw in agentic_keywords) and len(text) > 30

    def start(self) -> None:
        """Start the interactive session."""
        from ijachi_router.health import check_providers_quick, render_provider_card
        from ijachi_router.config import load_config

        # Show provider health card
        cfg = load_config()
        statuses = check_providers_quick(cfg)
        render_provider_card(statuses)

        # Load workspace memory
        from ijachi_router.agent import load_memory
        workspace_id = str(Path.cwd())
        mem = load_memory(workspace_id)
        if mem:
            console.print(Panel(
                f"[dim]{mem[:300]}...[/dim]" if len(mem) > 300 else f"[dim]{mem}[/dim]",
                title="[bold cyan]📝 Workspace Memory Loaded[/bold cyan]",
                border_style="dim cyan",
                padding=(0, 1),
            ))

        console.print(
            "\n[bold cyan]💬 ijachi-code Interactive Session[/bold cyan]  "
            "[dim]Type [bold]/help[/bold] for commands, [bold]exit[/bold] to quit[/dim]\n"
        )

        while True:
            try:
                self._render_status_bar()
                user_input = console.input("[bold cyan]ijachi>[/bold cyan] ").strip()

                if not user_input:
                    continue

                # Exit
                if user_input.lower() in {"exit", "quit", "q"}:
                    console.print("[dim]Session ended. Goodbye! 👋[/dim]")
                    break

                # Slash command
                if user_input.startswith("/"):
                    result = self._handle_slash(user_input)
                    if result is True:
                        break
                    continue

                # Route: agentic vs simple
                if self._is_agentic_task(user_input):
                    self._run_agentic(user_input)
                else:
                    self._run_simple(user_input)

            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Session interrupted. Goodbye! 👋[/dim]")
                break
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")
