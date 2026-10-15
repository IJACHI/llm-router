"""Full Claude Code-style interactive REPL with full slash commands and session continuity.

Document 2.2 & Document 6.2:
Interactive session with continuous session logging, checkpoints, slash commands,
and multiline input.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ijachi_router.agent.loop import AgentSessionLoop
from ijachi_router.context.memory import init_project_memory, load_project_memory
from ijachi_router.doctor import print_doctor_report
from ijachi_router.health import check_providers_quick, render_provider_card
from ijachi_router.session.store import SessionStore, list_sessions
from ijachi_router.ui.prompts import prompt_user_input
from ijachi_router.ui.render import (
    format_status_line,
    render_diff,
    render_markdown,
    render_turn_footer,
)

console = Console()

_HISTORY_FILE = Path.home() / ".ijachi-llmr" / "history.txt"


class InteractiveREPL:
    """Full-featured interactive REPL for ijachi-code."""

    def __init__(
        self,
        store: SessionStore,
        priority: str = "balanced",
        budget_usd: float | None = None,
        pinned_model: str | None = None,
        permission_mode: str = "ask",
    ):
        self.store = store
        self.state = store.state
        self.checkpoints = store.checkpoints
        if priority:
            self.state.priority = priority
        if budget_usd is not None:
            self.state.budget_usd = budget_usd
        if pinned_model:
            self.state.pinned_model = pinned_model

        self.loop = AgentSessionLoop(store=self.store, permission_mode=permission_mode)
        self.last_turn_cost: float = 0.0

        # Command directory
        self.commands = {
            "/help": "List commands and shortcuts",
            "/mode": "Configure routing mode [efficient | cheapest | best | best-fit]",
            "/autonomy": "Configure autonomy level [auto | semi-auto | manual]",
            "/auto": "Toggle autonomy level (auto / semi-auto / manual)",
            "/model": "Show, pin or unpin the model [id|auto]",
            "/priority": "Alias for /mode",
            "/permissions": "Alias for /autonomy",
            "/budget": "Show or set session budget [USD]",
            "/cost": "Spend, tokens, cache savings, per-model breakdown",
            "/why": "Explain the routing decision for the last turn",
            "/context": "Show context window usage by layer",
            "/compact": "Compact conversation into structured summary",
            "/clear": "Start a fresh session",
            "/resume": "Browse and resume previous sessions",
            "/sessions": "List previous sessions",
            "/undo": "Revert the last file change set to its checkpoint",
            "/checkpoint": "Create a named checkpoint [name]",
            "/diff": "Show changes against last checkpoint",
            "/memory": "View or edit project memory (IJACHI.md)",
            "/init": "Draft a project memory file for this repo",
            "/providers": "Show provider status and circuit breakers",
            "/doctor": "Run full environment and model diagnostics",
            "/update": "Check and pull latest updates from GitHub",
            "/exit": "Leave session and print cost summary",
        }

    def _toolbar_fn(self) -> str:
        mode = "pinned" if self.state.pinned_model else "auto"
        autonomy = getattr(self.loop.permissions, "mode", "manual")
        return format_status_line(
            mode=mode,
            model=self.state.current_model or self.state.pinned_model or "auto",
            ctx_percent=min(100, int((self.state.tokens_cached_estimate / 128_000) * 100)),
            last_cost=self.last_turn_cost,
            session_cost=self.state.total_cost_usd,
            budget_usd=self.state.budget_usd,
            routing_mode=self.state.priority or "efficient",
            autonomy_mode=autonomy,
        )
    def handle_command(self, cmd_line: str) -> bool:
        """Alias for handle_slash_command."""
        return self.handle_slash_command(cmd_line)

    def handle_slash_command(self, cmd_line: str) -> bool:
        """Handle slash command. Returns True if REPL should exit."""
        parts = cmd_line.strip().split(None, 1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            console.print(f"\n[dim]Session closed. Total spend: ${self.state.total_cost_usd:.4f}. Goodbye![/dim]\n")
            return True

        if cmd == "/help":
            t = Table(title="📖 ijachi-code Commands", border_style="cyan")
            t.add_column("Command", style="bold cyan")
            t.add_column("Description", style="white")
            for k, v in self.commands.items():
                t.add_row(k, v)
            console.print(t)
            console.print("\n[dim]Shortcuts: !<cmd> runs shell command, #<note> appends to IJACHI.md, @<path> links file[/dim]\n")
            return False

        if cmd == "/model":
            if not args or args == "show":
                curr = self.state.pinned_model or self.state.current_model or "auto"
                pin_status = "(pinned)" if self.state.pinned_model else "(auto-routing)"
                console.print(f"[bold cyan]Current model:[/bold cyan] {curr} {pin_status}\n")
            elif args == "auto":
                self.state.pinned_model = None
                console.print("[bold green]✓ Unpinned model. Auto-routing restored.[/bold green]\n")
            else:
                self.state.pinned_model = args
                console.print(f"[bold green]✓ Pinned session to model:[/bold green] {args}\n")
            return False

        if cmd in ("/mode", "/priority"):
            from ijachi_router.config import normalize_mode, save_user_priority
            if not args or args in ("show", "help", "list"):
                curr = normalize_mode(self.state.priority)
                table = Table(title="🧭 Routing Preference Modes", border_style="cyan")
                table.add_column("Key", style="bold", justify="center")
                table.add_column("Mode", style="bold cyan")
                table.add_column("Strategy & Philosophy", style="white")
                table.add_column("Status", justify="center")

                modes_info = [
                    ("1", "efficient", "(DEFAULT) Most efficient: balances cost and best fit (cheapest adequate model)", "green"),
                    ("2", "cheapest", "Only cheapest models/providers (prioritizes free/local & lowest cost)", "yellow"),
                    ("3", "best", "Best models/providers (high-capability & frontier model preference)", "cyan"),
                    ("4", "best-fit", "Best fit models/providers for the task irrespective of cost (0% cost penalty)", "magenta"),
                ]
                for key, name, desc, col in modes_info:
                    is_active = (curr == name)
                    status = f"[bold {col}]● ACTIVE[/bold {col}]" if is_active else "[dim]inactive[/dim]"
                    table.add_row(key, f"[{col}]{name}[/{col}]", desc, status)

                console.print(table)
                try:
                    choice = input("Select routing mode (1-4 or name) [Enter to keep current]: ").strip()
                    if choice:
                        args = choice
                    else:
                        console.print()
                        return False
                except (KeyboardInterrupt, EOFError):
                    console.print()
                    return False

            norm = normalize_mode(args)
            self.state.priority = norm
            self.loop.config.priority = norm
            save_user_priority(norm)
            labels = {
                "efficient": "Most Efficient (Cost & Best Fit Balanced - Default)",
                "cheapest": "Only Cheapest (Lowest Cost & Free Models)",
                "best": "Best Models (High Capability Bias)",
                "best-fit": "Best Fit Irrespective of Cost (Pure Task Quality)",
                "speed": "Speed (Lowest Latency)",
            }
            desc = labels.get(norm, norm)
            console.print(f"[bold green]✓ Routing preference set to:[/bold green] [bold cyan]{norm}[/bold cyan] · {desc}")
            console.print("[dim]Saved as your default preference in ~/.ijachi-llmr/config.yaml[/dim]\n")
            return False

        if cmd in ("/autonomy", "/permissions"):
            from ijachi_router.agent.permissions import normalize_permission_mode
            curr = getattr(self.loop.permissions, "mode", "manual")
            if not args or args in ("show", "help", "list"):
                table = Table(title="🛡️  Autonomy & Execution Permissions", border_style="cyan")
                table.add_column("Key", style="bold", justify="center")
                table.add_column("Autonomy Level", style="bold cyan")
                table.add_column("Approval Behavior", style="white")
                table.add_column("Status", justify="center")

                levels_info = [
                    ("1", "auto", "Fully automatic (no need for user approvals for safe actions)", "green"),
                    ("2", "semi-auto", "Semi-automatic (approvals for some: auto-approves edits, asks for shell execution)", "yellow"),
                    ("3", "manual", "Manual (needs approval for every major activity)", "cyan"),
                ]
                for key, name, desc, col in levels_info:
                    is_active = (curr == name)
                    status = f"[bold {col}]● ACTIVE[/bold {col}]" if is_active else "[dim]inactive[/dim]"
                    table.add_row(key, f"[{col}]{name}[/{col}]", desc, status)

                console.print(table)
                try:
                    choice = input("Select autonomy level (1-3 or name) [Enter to keep current]: ").strip()
                    if choice:
                        args = choice
                    else:
                        console.print()
                        return False
                except (KeyboardInterrupt, EOFError):
                    console.print()
                    return False

            norm = normalize_permission_mode(args)
            self.loop.permissions.mode = norm
            labels = {
                "auto": "Fully automatic (no need for user approvals for safe activities)",
                "semi-auto": "Semi-automatic (approvals for some activities)",
                "manual": "Manual (needs approval for every major activity)",
            }
            console.print(f"[bold green]✓ Autonomy level set to:[/bold green] [bold cyan]{norm}[/bold cyan] · {labels.get(norm, norm)}\n")
            return False

        if cmd == "/auto":
            from ijachi_router.agent.permissions import normalize_permission_mode
            if args:
                norm = normalize_permission_mode(args)
            else:
                cycle = {"manual": "semi-auto", "semi-auto": "auto", "auto": "manual"}
                curr = getattr(self.loop.permissions, "mode", "manual")
                norm = cycle.get(curr, "semi-auto")

            self.loop.permissions.mode = norm
            labels = {
                "auto": "Fully automatic (no need for user approvals)",
                "semi-auto": "Semi-automatic (approvals for some activities)",
                "manual": "Manual (needs approval for every major activity)",
            }
            console.print(f"[bold green]✓ Autonomy toggled to:[/bold green] [bold cyan]{norm}[/bold cyan] ({labels.get(norm, norm)})\n")
            return False

        if cmd == "/budget":
            if args:
                try:
                    self.state.budget_usd = float(args.lstrip("$"))
                    console.print(f"[bold green]✓ Session budget cap set to:[/bold green] ${self.state.budget_usd:.2f}\n")
                except ValueError:
                    console.print("[bold red]Invalid budget format. Usage: /budget 2.50[/bold red]\n")
            else:
                b_str = f"${self.state.budget_usd:.2f}" if self.state.budget_usd is not None else "None"
                console.print(f"[bold cyan]Session budget:[/bold cyan] {b_str} (Current spend: ${self.state.total_cost_usd:.4f})\n")
            return False

        if cmd == "/cost":
            t = Table(title="💰 Session Spend Breakdown", border_style="cyan")
            t.add_column("Model", style="bold cyan")
            t.add_column("Cost (USD)", style="green")
            for m, c in self.state.model_costs.items():
                t.add_row(m, f"${c:.4f}")
            t.add_row("[bold]Total[/bold]", f"[bold green]${self.state.total_cost_usd:.4f}[/bold green]")
            console.print(t)
            console.print(f"[dim]Tokens: {self.state.total_input_tokens:,} in / {self.state.total_output_tokens:,} out[/dim]\n")
            return False

        if cmd == "/why":
            if self.loop.last_explanation:
                console.print(Panel(
                    self.loop.last_explanation.format_terminal_text(),
                    border_style="cyan",
                ))
            else:
                console.print("[dim]No routing decisions recorded yet in this session.[/dim]\n")
            return False

        if cmd == "/context":
            events = self.store.read_events()
            ctx = self.loop.assembler.assemble(
                state=self.state,
                events=events,
                new_user_message="",
                model_window=128_000,
            )
            t = Table(title="🧠 Context Window Usage by Layer", border_style="cyan")
            t.add_column("Layer", style="bold white")
            t.add_column("Estimated Tokens", style="cyan")
            for k, v in ctx.layers.to_dict().items():
                t.add_row(k, f"{v:,}")
            t.add_row("[bold]Total Assembled[/bold]", f"[bold green]{ctx.total_tokens:,}[/bold green]")
            console.print(t)
            console.print()
            return False

        if cmd == "/compact":
            from ijachi_router.context.compaction import CompactionEngine
            events = self.store.read_events()
            CompactionEngine.compact_events(events, self.state, focus=args)
            self.store.save_state()
            console.print("[bold green]✓ Session context compacted into structured summary.[/bold green]\n")
            return False

        if cmd == "/clear":
            self.store.save_state()
            console.print("[bold green]✓ Session state checkpointed. Starting fresh session...[/bold green]\n")
            self.store = SessionStore(workspace_dir=Path(self.state.workspace_dir))
            self.state = self.store.state
            self.loop = AgentSessionLoop(store=self.store)
            return False

        if cmd in ("/resume", "/sessions"):
            all_s = list_sessions()
            t = Table(title="📂 Available Sessions", border_style="cyan")
            t.add_column("Session ID", style="bold cyan")
            t.add_column("Turns", style="white")
            t.add_column("Cost", style="green")
            t.add_column("Workspace", style="dim")
            for s in all_s[:10]:
                t.add_row(s["id"], str(s["turns"]), f"${s['cost']:.4f}", s["workspace"])
            console.print(t)
            if args:
                try:
                    self.store = SessionStore(session_id=args, workspace_dir=Path.cwd())
                    self.state = self.store.state
                    self.loop = AgentSessionLoop(store=self.store)
                    console.print(f"[bold green]✓ Resumed session {args}[/bold green]\n")
                except Exception as e:
                    console.print(f"[bold red]Failed to resume {args}: {e}[/bold red]\n")
            return False

        if cmd == "/undo":
            ok, msg = self.store.checkpoints.undo_last()
            color = "green" if ok else "yellow"
            console.print(f"[{color}]{msg}[/{color}]\n")
            return False

        if cmd == "/checkpoint":
            name = args or f"checkpoint_{len(self.store.checkpoints.checkpoint_stack) + 1}"
            touched = list(self.state.working_set.keys())
            if not touched and hasattr(self.store, "workspace_dir"):
                touched = [str(p) for p in self.store.workspace_dir.glob("*") if p.is_file() and not p.name.startswith(".")]
            cp_id = self.store.checkpoints.create_checkpoint(name, touched)
            console.print(f"[bold green]✓ Created checkpoint '{name}' ({cp_id}) covering {len(touched)} files.[/bold green]\n")
            return False

        if cmd == "/diff":
            diff = self.store.checkpoints.diff_from_checkpoint()
            render_diff(diff)
            return False

        if cmd == "/memory":
            mem = load_project_memory()
            if mem:
                console.print(Panel(mem, title="[bold cyan]📝 Project Memory (IJACHI.md)[/bold cyan]", border_style="cyan"))
            else:
                console.print("[dim]No IJACHI.md found. Use /init to draft one.[/dim]\n")
            return False

        if cmd == "/init":
            init_project_memory()
            console.print("[bold green]✓ Created project memory file IJACHI.md[/bold green]\n")
            return False

        if cmd == "/providers":
            render_provider_card(check_providers_quick(self.loop.config))
            return False

        if cmd == "/doctor":
            print_doctor_report()
            return False

        if cmd == "/update":
            from ijachi_router.updater import update_ijachi
            msg = update_ijachi()
            console.print(f"[bold cyan]{msg}[/bold cyan]\n")
            return False

        console.print(f"[bold red]Unknown command:[/bold red] {cmd} (Type /help for command list)\n")
        return False

    def start(self) -> None:
        """Start the interactive loop."""
        r_mode = self.state.priority or "efficient"
        a_mode = getattr(self.loop.permissions, "mode", "manual")
        banner = (
            f"[bold cyan]ijachi-code v1.0[/bold cyan]  ·  [dim]{self.state.workspace_dir}[/dim]\n"
            f"[white]Autonomous pairing assistant with continuous cross-model session routing.[/white]\n\n"
            f"  ⚡ [bold]Routing Mode:[/bold]    [bold green]{r_mode.upper()}[/bold green] (Cost/fit balanced) · Type [bold cyan]/mode[/bold cyan] to change\n"
            f"  🛡️  [bold]Autonomy Level:[/bold]  [bold yellow]{a_mode.upper()}[/bold yellow] · Type [bold cyan]/auto[/bold cyan] to toggle or [bold cyan]/autonomy[/bold cyan]\n"
            f"  💡 [bold]Shortcuts:[/bold]       [cyan]/help[/cyan] (commands) · [cyan]![/cyan]cmd (shell) · [cyan]#[/cyan]note (session ledger)"
        )
        console.print(Panel(banner, border_style="cyan", padding=(0, 2)))

        while True:
            user_input = prompt_user_input(
                commands=self.commands,
                toolbar_fn=self._toolbar_fn,
                history_file=_HISTORY_FILE,
            )

            if user_input is None:
                continue

            if user_input == "__EXIT__":
                console.print(f"\n[dim]Session closed. Total spend: ${self.state.total_cost_usd:.4f}. Goodbye![/dim]\n")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Check slash command
            if user_input.startswith("/"):
                should_exit = self.handle_slash_command(user_input)
                if should_exit:
                    break
                continue

            # Check shell command shortcut (!cmd)
            if user_input.startswith("!"):
                shell_cmd = user_input[1:].strip()
                res = self.loop.tools.tool_bash({"command": shell_cmd})
                console.print(Panel(res.output, title=f"[bold yellow]! {shell_cmd}[/bold yellow]"))
                continue

            # Check note shortcut (#note)
            if user_input.startswith("#"):
                note = user_input[1:].strip()
                self.state.ledger.record_fact(note, category="user_note", turn=self.state.turn_count)
                console.print(f"[bold green]✓ Recorded note to session ledger:[/bold green] {note}\n")
                continue

            # Process prompt
            try:
                turn_res = self.loop.execute_turn(user_input)
                self.last_turn_cost = turn_res.cost_usd

                render_markdown(turn_res.text)
                render_turn_footer(
                    model=f"{turn_res.provider_used}/{turn_res.model_used}",
                    in_tokens=turn_res.input_tokens,
                    out_tokens=turn_res.output_tokens,
                    cost_usd=turn_res.cost_usd,
                    latency_sec=turn_res.latency_sec,
                    cached_tokens=self.state.tokens_cached_estimate,
                )
                console.print()

            except Exception as e:
                console.print(f"[bold red]Turn error:[/bold red] {e}\n")
