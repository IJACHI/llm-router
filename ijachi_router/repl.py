"""Rich Interactive REPL for ijachi-code.

Uses prompt_toolkit for a best-in-class terminal input experience:
- ↑/↓ arrow keys to cycle through command history
- Persistent history file (~/.ijachi-llmr/history.txt) — survives across sessions
- Visually distinct bordered input area at the bottom of the terminal
- Slash-command autocompletion as you type
- Bottom toolbar showing: git branch · session cost · model · auto/plan flags
- Rich bordered response panels with Markdown rendering above the input field
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

# prompt_toolkit: powers history + styled input field
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

console = Console()

_HISTORY_FILE = Path.home() / ".ijachi-llmr" / "history.txt"
_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Slash command registry
# ---------------------------------------------------------------------------

@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable[["RichREPL", str], bool]  # True = exit session


_SLASH_COMMANDS: dict[str, SlashCommand] = {}


def _register(name: str, description: str):
    def decorator(fn):
        _SLASH_COMMANDS[name] = SlashCommand(name=name, description=description, handler=fn)
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _git_info() -> tuple[str, int]:
    """Return (branch_name, dirty_file_count)."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        return branch, len([l for l in dirty.splitlines() if l.strip()])
    except Exception:
        return "", 0


def _render_response(text: str, model_used: str, cost_usd: float) -> None:
    """Render a rich-formatted response panel above the input field."""
    header = Text()
    header.append("🤖 ", style="bold")
    header.append(model_used, style="bold cyan")
    header.append(f"  💰 ${cost_usd:.4f}", style="dim green")

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
    console.print()  # breathing room before input field redraws


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------

@_register("/help", "Show all available commands")
def _cmd_help(repl: "RichREPL", args: str) -> bool:
    from rich.table import Table
    table = Table(title="📖 IJACHI CODE Commands", border_style="bright_blue", show_header=True)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description", style="white")
    for cmd in _SLASH_COMMANDS.values():
        table.add_row(cmd.name, cmd.description)
    table.add_row("[dim]exit / quit / q[/dim]", "[dim]End the session[/dim]")
    console.print(table)
    console.print()
    return False


@_register("/clear", "Clear conversation context and reset session cost")
def _cmd_clear(repl: "RichREPL", args: str) -> bool:
    repl.history_ctx.clear()
    repl.session_cost = 0.0
    console.print("[bold green]✓ Context cleared.[/bold green] Session cost reset to $0.00\n")
    return False


@_register("/status", "Show provider, model, cost, and git branch")
def _cmd_status(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.health import check_providers_quick, render_provider_card
    from ijachi_router.config import load_config
    cfg = load_config()
    statuses = check_providers_quick(cfg)
    render_provider_card(statuses)
    branch, dirty = _git_info()
    if branch:
        dirty_str = f" ({dirty} modified)" if dirty else ""
        console.print(f"[bold cyan]⎇ Branch:[/bold cyan] {branch}{dirty_str}")
    console.print(f"[bold cyan]💰 Session cost:[/bold cyan] ${repl.session_cost:.4f}")
    console.print(f"[bold cyan]💬 Context messages:[/bold cyan] {len(repl.history_ctx)}\n")
    return False


@_register("/providers", "Show active provider health card")
def _cmd_providers(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.health import check_providers_quick, render_provider_card
    from ijachi_router.config import load_config
    cfg = load_config()
    render_provider_card(check_providers_quick(cfg))
    return False


@_register("/auto", "Toggle auto-approval for all file operations")
def _cmd_auto(repl: "RichREPL", args: str) -> bool:
    repl.auto_approve = not repl.auto_approve
    state = "[bold green]ON[/bold green]" if repl.auto_approve else "[bold red]OFF[/bold red]"
    console.print(f"[bold cyan]Auto-approval:[/bold cyan] {state}\n")
    return False


@_register("/plan", "Toggle plan-first mode (shows plan before executing)")
def _cmd_plan(repl: "RichREPL", args: str) -> bool:
    repl.plan_mode = not repl.plan_mode
    state = "[bold green]ON[/bold green]" if repl.plan_mode else "[bold yellow]OFF[/bold yellow]"
    console.print(f"[bold cyan]Plan-first mode:[/bold cyan] {state}\n")
    return False


@_register("/memory", "Show or clear persistent session memory  (use: /memory clear)")
def _cmd_memory(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.agent import load_memory, save_memory
    workspace_id = str(Path.cwd())
    if args.strip() == "clear":
        save_memory(workspace_id, "")
        console.print("[bold green]✓ Memory cleared.[/bold green]\n")
    else:
        mem = load_memory(workspace_id)
        if mem:
            console.print(Panel(mem, title="[bold cyan]📝 Session Memory[/bold cyan]", border_style="cyan"))
        else:
            console.print("[dim]No memory for this workspace yet.[/dim]")
    console.print()
    return False


@_register("/compact", "Manually compress conversation history to save context")
def _cmd_compact(repl: "RichREPL", args: str) -> bool:
    if not repl.history_ctx:
        console.print("[dim]Nothing to compact.[/dim]\n")
        return False
    console.print("[bold cyan]🔄 Compacting context...[/bold cyan]")
    from ijachi_router.core import route
    full = "\n".join(m.get("content", "") for m in repl.history_ctx[-20:])
    res = route(
        f"Summarize this conversation in 3-5 bullet points preserving key decisions and code changes:\n\n{full[:6000]}",
        priority="cost",
    )
    summary = res.text.strip()
    repl.history_ctx.clear()
    repl.history_ctx.append({"role": "system", "content": f"[Compacted context]\n{summary}"})
    console.print(f"[bold green]✓ Compacted {len(full)} chars → {len(summary)} chars[/bold green]\n")
    return False


# ---------------------------------------------------------------------------
# prompt_toolkit styling
# ---------------------------------------------------------------------------

_PT_STYLE = Style.from_dict({
    # Bottom toolbar
    "bottom-toolbar":           "bg:#1a1a2e fg:#7ecfff",
    "bottom-toolbar.text":      "bg:#1a1a2e fg:#7ecfff",
    "bottom-toolbar.git":       "bg:#1a1a2e fg:#4fc3f7 bold",
    "bottom-toolbar.cost":      "bg:#1a1a2e fg:#69ff47 bold",
    "bottom-toolbar.flag":      "bg:#1a1a2e fg:#ffd700 bold",
    "bottom-toolbar.sep":       "bg:#1a1a2e fg:#444466",
    # Prompt itself
    "prompt":                   "fg:#00e5ff bold",
    "prompt.arrow":             "fg:#444466",
    # Input area box line
    "rprompt":                  "fg:#444466",
})


def _make_completer() -> WordCompleter:
    """Autocomplete for slash commands."""
    return WordCompleter(
        list(_SLASH_COMMANDS.keys()) + ["exit", "quit"],
        sentence=True,
        pattern=None,
    )


# ---------------------------------------------------------------------------
# Main REPL class
# ---------------------------------------------------------------------------

@dataclass
class RichREPL:
    """prompt_toolkit powered interactive REPL for ijachi-code."""

    priority: str = "balanced"
    plan_mode: bool = False
    auto_approve: bool = False
    history_ctx: list[dict] = field(default_factory=list)   # in-session message context
    session_cost: float = 0.0

    # ------------------------------------------------------------------ #
    # Bottom toolbar (rendered by prompt_toolkit on every keystroke)
    # ------------------------------------------------------------------ #

    def _toolbar(self) -> HTML:
        branch, dirty = _git_info()
        git_part = f"⎇ {branch}" if branch else ""
        if dirty:
            git_part += f" ({dirty}✎)"

        cost_part = f"💰 ${self.session_cost:.4f}"
        flags = []
        if self.auto_approve:
            flags.append("AUTO")
        if self.plan_mode:
            flags.append("PLAN")
        flag_part = " · ".join(flags)

        parts = [p for p in [git_part, cost_part, flag_part] if p]
        toolbar_text = "  │  ".join(parts)

        return HTML(
            f'<bottom-toolbar>'
            f'  <b>⚡ IJACHI</b>  <sep>│</sep>  {toolbar_text}'
            f'  <sep>  [/help for commands]</sep>'
            f'</bottom-toolbar>'
        )

    # ------------------------------------------------------------------ #
    # prompt_toolkit session factory
    # ------------------------------------------------------------------ #

    def _make_session(self) -> PromptSession:
        kb = KeyBindings()

        @kb.add("c-l")
        def _clear_screen(event):
            """Ctrl+L clears the terminal screen."""
            event.app.renderer.reset()
            import os
            os.system("clear")

        return PromptSession(
            history=FileHistory(str(_HISTORY_FILE)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=_make_completer(),
            complete_while_typing=True,
            style=_PT_STYLE,
            bottom_toolbar=self._toolbar,
            key_bindings=kb,
            mouse_support=False,
            wrap_lines=True,
        )

    # ------------------------------------------------------------------ #
    # Routing helpers
    # ------------------------------------------------------------------ #

    def _is_agentic_task(self, text: str) -> bool:
        agentic_keywords = [
            "build", "create", "write", "edit", "fix", "refactor", "implement",
            "add", "remove", "delete", "read", "open", "run", "test", "deploy",
            "install", "scaffold", "generate", "update", "modify",
        ]
        lower = text.lower()
        return any(kw in lower for kw in agentic_keywords) and len(text) > 30

    def _run_agentic(self, task: str) -> None:
        from ijachi_router.agent import AgenticRouter, save_memory
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
                console.print("[dim]Plan rejected. Task cancelled.[/dim]\n")
                return

        result = agent.run(task)
        self.session_cost += result.total_cost_usd
        _render_response(
            result.final_text,
            model_used=f"agentic/{self.priority}",
            cost_usd=result.total_cost_usd,
        )
        save_memory(str(Path.cwd()), f"Task: {task[:200]}\nResult: {result.final_text[:500]}")

    def _run_simple(self, prompt: str) -> None:
        from ijachi_router.core import route
        res = route(prompt, priority=self.priority)
        self.session_cost += res.cost_usd
        _render_response(res.text, model_used=res.model_used, cost_usd=res.cost_usd)

    # ------------------------------------------------------------------ #
    # Main session loop
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the interactive session."""
        # Provider health card at startup
        from ijachi_router.health import check_providers_quick, render_provider_card
        from ijachi_router.config import load_config
        from ijachi_router.agent import load_memory

        render_provider_card(check_providers_quick(load_config()))

        # Load workspace memory
        mem = load_memory(str(Path.cwd()))
        if mem:
            console.print(Panel(
                f"[dim]{mem[:300]}{'...' if len(mem) > 300 else ''}[/dim]",
                title="[bold cyan]📝 Workspace Memory Loaded[/bold cyan]",
                border_style="dim cyan",
                padding=(0, 1),
            ))
            console.print()

        console.print(
            "[bold cyan]💬 ijachi-code Interactive Session[/bold cyan]  "
            "[dim]↑↓ history · Tab autocomplete · Ctrl+L clear screen · [bold]/help[/bold] for commands[/dim]\n"
        )

        session = self._make_session()

        while True:
            try:
                # Prompt: styled chevron with a clear visual input field
                user_input = session.prompt(
                    HTML('<prompt><b>❯ ijachi</b></prompt> '),
                    style=_PT_STYLE,
                    bottom_toolbar=self._toolbar,
                    rprompt=HTML('<rprompt>⏎ send</rprompt>'),
                ).strip()

            except KeyboardInterrupt:
                # Ctrl+C cancels current input line — don't exit
                console.print()
                continue
            except EOFError:
                # Ctrl+D exits cleanly
                console.print("\n[dim]Session ended. Goodbye! 👋[/dim]")
                break

            if not user_input:
                continue

            # Exit words
            if user_input.lower() in {"exit", "quit", "q"}:
                console.print("[dim]Session ended. Goodbye! 👋[/dim]")
                break

            # Slash commands
            if user_input.startswith("/"):
                parts = user_input.strip().split(None, 1)
                cmd_name = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                if cmd_name in _SLASH_COMMANDS:
                    should_exit = _SLASH_COMMANDS[cmd_name].handler(self, args)
                    if should_exit:
                        break
                else:
                    console.print(
                        f"[bold red]Unknown command:[/bold red] {cmd_name}  "
                        f"[dim]→ type [bold]/help[/bold] for all commands[/dim]\n"
                    )
                continue

            # Route: agentic vs simple
            try:
                if self._is_agentic_task(user_input):
                    self._run_agentic(user_input)
                else:
                    self._run_simple(user_input)
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}\n")
