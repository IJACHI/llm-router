"""Rich Interactive REPL for ijachi-code.

Architecture:
- Rich prints all conversation output (AI panels, user bubbles, separators)
- prompt_toolkit Application renders a FRAMED input box at the bottom
  (actual Unicode border drawn around the typing area, with ↑↓ history)
- Each "round-trip" exits the Application, prints the response via Rich,
  then reopens the Application for the next input — clean and reliable.

Visual layout:
  ┌── YOU ───────────────────────────────────────────────┐
  │  build me a FastAPI auth service                     │
  └──────────────────────────────────────────────────────┘

  ╔══ 🤖 IJACHI · gemini-3.6-flash · $0.0003 ══════════╗
  ║  Here's the FastAPI service:                         ║
  ║  ...                                                 ║
  ╚══════════════════════════════════════════════════════╝

  ╭─ ✍  Type a message ─────────────────────────────────╮
  │  █                                                   │
  ╰─ ⎇ main · 💰 $0.0003 · ↑↓ history · Tab autocomplete╯
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
from rich.rule import Rule
from rich.text import Text

from prompt_toolkit import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

console = Console()

_HISTORY_FILE = Path.home() / ".ijachi-llmr" / "history.txt"
_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

# Shared FileHistory instance so ↑↓ works across the session
_FILE_HISTORY = FileHistory(str(_HISTORY_FILE))


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


# ---------------------------------------------------------------------------
# Message rendering (Rich panels)
# ---------------------------------------------------------------------------

def _render_user_message(text: str) -> None:
    """Render a clearly styled 'YOU' bubble."""
    console.print(Panel(
        f"[bold white]{text}[/bold white]",
        title="[bold dim white]▸ YOU[/bold dim white]",
        title_align="left",
        border_style="dim white",
        padding=(0, 2),
    ))


def _render_ai_response(text: str, model_used: str, cost_usd: float) -> None:
    """Render a distinctly styled IJACHI response panel."""
    try:
        content = Markdown(text)
    except Exception:
        content = Text(text)

    title = Text()
    title.append("🤖  IJACHI", style="bold cyan")
    title.append("  ·  ", style="dim")
    title.append(model_used, style="cyan")
    title.append("  ·  ", style="dim")
    title.append(f"${cost_usd:.4f}", style="bold green")

    console.print(Panel(
        content,
        title=title,
        title_align="left",
        border_style="bright_cyan",
        style="on grey7",          # dark background makes AI panel clearly distinct
        padding=(1, 2),
    ))
    console.print()


# ---------------------------------------------------------------------------
# Framed input box (prompt_toolkit Application)
# ---------------------------------------------------------------------------

_INPUT_STYLE = Style.from_dict({
    # Frame border
    "frame":                   "fg:#00e5ff",
    "frame.border":            "fg:#00e5ff",
    "frame.label":             "fg:#00e5ff bold",
    # Input text inside frame
    "":                        "fg:#ffffff bg:#0d1117",
    # Bottom toolbar
    "toolbar":                 "bg:#0d1117 fg:#4a9eff",
    "toolbar.key":             "bg:#0d1117 fg:#00e5ff bold",
})


def _get_completer() -> WordCompleter:
    from ijachi_router.skills_loader import discover_skills
    skills = discover_skills(Path.cwd())
    skill_cmds = [f"/{s}" for s in skills.keys()]
    all_cmds = sorted(set(list(_SLASH_COMMANDS.keys()) + skill_cmds + ["exit", "quit"]))
    return WordCompleter(all_cmds, sentence=True)


def _prompt_input(toolbar_fn) -> str | None:
    """
    Open a bordered prompt_toolkit Application for one round of input.
    Returns the submitted text, or None on Ctrl+C / Ctrl+D.
    """
    submitted: list[str] = []
    cancelled: list[bool] = []

    buf = Buffer(
        history=_FILE_HISTORY,
        completer=_get_completer(),
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
        name="main_input",
    )

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        text = buf.text.strip()
        submitted.append(text)
        event.app.exit()

    @kb.add("c-c")
    def _interrupt(event):
        # Cancel current line without exiting the session
        cancelled.append(True)
        event.app.exit()

    @kb.add("c-d")
    def _eof(event):
        submitted.append("__EXIT__")
        event.app.exit()

    @kb.add("c-l")
    def _clear(event):
        os.system("clear")
        event.app.renderer.reset()

    layout = Layout(
        HSplit([
            Frame(
                Window(
                    BufferControl(buffer=buf),
                    height=1,
                    get_line_prefix=lambda i, wrap_count: "  ",
                ),
                title=" ✍  Type a message ",
                style="class:frame",
            ),
            Window(
                FormattedTextControl(toolbar_fn),
                height=1,
                style="class:toolbar",
            ),
        ])
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=_INPUT_STYLE,
        full_screen=False,
        mouse_support=False,
    )
    app.run()

    if cancelled:
        return None  # Ctrl+C → caller loops again
    return submitted[0] if submitted else None


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------

@_register("/help", "Show all available commands")
def _cmd_help(repl: "RichREPL", args: str) -> bool:
    from rich.table import Table
    table = Table(title="📖 IJACHI Commands", border_style="bright_blue", show_header=True)
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
    os.system("clear")
    console.print("[bold green]✓ Context cleared.[/bold green]  Session cost reset to $0.00\n")
    return False


@_register("/status", "Show provider, model, cost, and git branch")
def _cmd_status(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.health import check_providers_quick, render_provider_card
    from ijachi_router.config import load_config
    render_provider_card(check_providers_quick(load_config()))
    branch, dirty = _git_info()
    if branch:
        dirty_str = f" ({dirty} modified)" if dirty else ""
        console.print(f"[bold cyan]⎇  Branch:[/bold cyan] {branch}{dirty_str}")
    console.print(f"[bold cyan]💰 Session cost:[/bold cyan] ${repl.session_cost:.4f}\n")
    return False


@_register("/providers", "Show active provider health card")
def _cmd_providers(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.health import check_providers_quick, render_provider_card
    from ijachi_router.config import load_config
    render_provider_card(check_providers_quick(load_config()))
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


@_register("/memory", "View or update dual-scope memory (/memory clear | /memory user <note>)")
def _cmd_memory(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.agent import load_memory, save_memory
    args_s = args.strip()
    if args_s == "clear":
        save_memory(str(Path.cwd()), "", scope="project")
        console.print("[bold green]✓ Project workspace memory cleared.[/bold green]\n")
    elif args_s.startswith("user "):
        note = args_s[5:].strip()
        save_memory(str(Path.cwd()), note, scope="user")
        console.print(f"[bold green]✓ Saved global user preference:[/bold green] {note}\n")
    else:
        mem = load_memory(str(Path.cwd()), scope="all")
        if mem:
            console.print(Panel(mem, title="[bold cyan]📝 Dual-Scope Memory (User + Project)[/bold cyan]", border_style="cyan"))
        else:
            console.print("[dim]No memory saved yet. Use '/memory user <note>' to set global preferences.[/dim]")
    console.print()
    return False


@_register("/skills", "List all available skills (built-in and custom markdown skills)")
def _cmd_skills(repl: "RichREPL", args: str) -> bool:
    from ijachi_router.skills_loader import discover_skills
    from rich.table import Table
    skills = discover_skills(Path.cwd())
    table = Table(title="⚡ IJACHI Skills", border_style="bright_blue", show_header=True)
    table.add_column("Skill / Command", style="bold cyan")
    table.add_column("Scope", style="dim yellow")
    table.add_column("Description", style="white")
    for s in skills.values():
        table.add_row(f"/{s.name}", s.scope, s.description)
    console.print(table)
    console.print("[dim]Create custom skills by dropping *.md files in .ijachi/skills/ or ~/.ijachi-llmr/skills/[/dim]\n")
    return False


@_register("/compact", "Compress conversation history to save context tokens")
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
    console.print(f"[bold green]✓ Compacted {len(full):,} chars → {len(summary):,} chars[/bold green]\n")
    return False


# ---------------------------------------------------------------------------
# Main REPL class
# ---------------------------------------------------------------------------

@dataclass
class RichREPL:
    """
    ijachi-code interactive session.
    Rich handles output. prompt_toolkit Application handles the framed input box.
    """

    priority: str = "balanced"
    plan_mode: bool = False
    auto_approve: bool = False
    history_ctx: list[dict] = field(default_factory=list)
    session_cost: float = 0.0

    def _toolbar_text(self) -> HTML:
        """Bottom toolbar shown inside the input frame."""
        branch, dirty = _git_info()
        git_str = f"⎇ {branch}" + (f" ({dirty}✎)" if dirty else "")  if branch else ""
        cost_str = f"💰 ${self.session_cost:.4f}"
        flags = "  AUTO" if self.auto_approve else ""
        flags += "  PLAN" if self.plan_mode else ""
        hint = "↑↓ history · Tab complete · Ctrl+C cancel · Ctrl+D exit"
        parts = [p for p in [git_str, cost_str, flags] if p]
        left = "  ⚡ IJACHI  │  " + "  ·  ".join(parts) if parts else "  ⚡ IJACHI"
        right = f"  {hint}  "
        return HTML(f"{left}{right}")

    def _is_agentic_task(self, text: str) -> bool:
        keywords = [
            "build", "create", "write", "edit", "fix", "refactor", "implement",
            "add", "remove", "delete", "read", "open", "run", "test", "deploy",
            "install", "scaffold", "generate", "update", "modify",
        ]
        return any(kw in text.lower() for kw in keywords) and len(text) > 30

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

        console.print("[dim]Running agentic task...[/dim]")
        result = agent.run(task)
        self.session_cost += result.total_cost_usd
        _render_ai_response(
            result.final_text,
            model_used=f"agentic/{self.priority}",
            cost_usd=result.total_cost_usd,
        )
        save_memory(str(Path.cwd()), f"Task: {task[:200]}\nResult: {result.final_text[:500]}")

    def _run_simple(self, prompt: str) -> None:
        from ijachi_router.core import route
        console.print("[dim]Routing...[/dim]")
        res = route(prompt, priority=self.priority)
        self.session_cost += res.cost_usd
        _render_ai_response(res.text, model_used=res.model_used, cost_usd=res.cost_usd)

    def start(self) -> None:
        """Start the interactive session."""
        from ijachi_router.health import check_providers_quick, render_provider_card
        from ijachi_router.config import load_config
        from ijachi_router.agent import load_memory

        # --- Startup splash ---
        render_provider_card(check_providers_quick(load_config()))

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
            "[bold cyan]💬 ijachi-code[/bold cyan]  "
            "[dim]Type a message below — Ctrl+C to cancel input · Ctrl+D to quit[/dim]\n"
        )

        # --- Main loop ---
        while True:
            user_input = _prompt_input(self._toolbar_text)

            # Ctrl+C → cancelled current line, loop again
            if user_input is None:
                console.print()
                continue

            # Ctrl+D → exit
            if user_input == "__EXIT__":
                console.print("\n[dim]Session ended. Goodbye! 👋[/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Exit words
            if user_input.lower() in {"exit", "quit", "q"}:
                console.print("[dim]Session ended. Goodbye! 👋[/dim]")
                break

            # Show user message as a styled panel
            _render_user_message(user_input)

            # Slash commands
            if user_input.startswith("/"):
                parts = user_input.split(None, 1)
                cmd_name = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                if cmd_name in _SLASH_COMMANDS:
                    should_exit = _SLASH_COMMANDS[cmd_name].handler(self, args)
                    if should_exit:
                        break
                    continue

                # Check if command matches a registered skill (built-in, user, or project)
                from ijachi_router.skills_loader import discover_skills
                skills = discover_skills(Path.cwd())
                skill_key = cmd_name.lstrip("/")
                if skill_key in skills:
                    skill = skills[skill_key]
                    rendered_task = skill.render(args)
                    console.print(
                        f"[bold cyan]⚡ Executing skill: [bold magenta]/{skill.name}[/bold magenta] "
                        f"[dim]({skill.description})[/dim][/bold cyan]\n"
                    )
                    self._run_agentic(rendered_task)
                    continue

                console.print(
                    f"[bold red]Unknown command:[/bold red] {cmd_name}  "
                    "[dim]→ type [bold]/help[/bold] or [bold]/skills[/bold] for available commands[/dim]\n"
                )
                continue

            # Route to AI
            try:
                if self._is_agentic_task(user_input):
                    self._run_agentic(user_input)
                else:
                    self._run_simple(user_input)
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}\n")
