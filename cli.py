"""ijachi-router — CLI entry point for ijachi-llm-router.

Commands
--------
  ijachi-router route "<prompt>"   Route a prompt, print response + cost footer.
  ijachi-router "<prompt>"         Alias: same as route (for convenience).
  ijachi-router stats              Show spend/latency table.
  ijachi-router providers          List which providers have keys configured (alias: provider).
  ijachi-router update-catalog     Fetch dynamic model catalog & pricing updates.
  ijachi-router train              Retrain the classifier from data/train_data.csv.
  ijachi-router serve              [PRO] Launch REST API gateway & dashboard.
  ijachi-router dashboard          [PRO] Open web telemetry dashboard in browser.
  ijachi-router license            Manage Pro license keys.
  ijachi-router skills             [SKILLS] List, run, and install skills.
  ijachi-router theme <name>       Switch the active UI theme.
"""

from __future__ import annotations

import click


class RouterCLI(click.Group):
    """Custom Click Group that handles command aliases and bare prompt routing."""

    def get_command(self, ctx, cmd_name):
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        aliases = {
            "provider": "providers",
        }
        if cmd_name in aliases:
            return super().get_command(ctx, aliases[cmd_name])
        return None

    def parse_args(self, ctx, args):
        if args and not args[0].startswith("-"):
            cmd_name = args[0]
            if cmd_name not in self.commands and cmd_name not in {"provider"}:
                args.insert(0, "route")
        return super().parse_args(ctx, args)


@click.group(cls=RouterCLI, invoke_without_command=True)
@click.pass_context
def main(ctx):
    """ijachi-llm-router: one prompt, best model, automatic fallback."""
    if ctx.invoked_subcommand is None:
        from ijachi_router.wizard import LauncherWizard
        from ijachi_router.providers.base import ProviderError
        wizard = LauncherWizard()
        wizard.run_interactive_setup()
        try:
            ctx.invoke(chat_cmd)
        except ProviderError as exc:
            click.echo(click.style(f"\n✗ Provider error: {exc}", fg="red"))
            click.echo(click.style("  Run 'ijachi keys set <provider> <key>' to configure a provider, then try again.", fg="yellow"))


@main.command(name="setup")
def setup_cmd():
    """[LAUNCHER] Run interactive provider API key setup wizard."""
    from ijachi_router.wizard import LauncherWizard

    wizard = LauncherWizard()
    wizard.run_interactive_setup()


@main.command(name="launcher")
def launcher_cmd():
    """[LAUNCHER] Display compatible LLM providers and active key status."""
    from ijachi_router.wizard import LauncherWizard

    LauncherWizard.print_welcome_table()


@main.command(name="route")
@click.argument("prompt")
@click.option("--priority", "-p",
              type=click.Choice(["cost", "speed", "quality", "balanced"]),
              default=None,
              help="Override routing priority for this call.")
@click.option("--max-cost", "-m", type=float, default=None,
              help="Max USD per call (skips models that exceed this).")
@click.option("--humanize", "-H",
              type=click.Choice(["light", "full", "off"]),
              default="light",
              show_default=True,
              help="Humanization mode: light (safe for docs), full (strip all AI artifacts), off (raw output).")
@click.option("--stream", "-s", is_flag=True, default=False, help="Stream response tokens in real-time.")
@click.option("--models-yaml", default=None, hidden=True,
              help="Custom path to models.yaml.")
def route_cmd(prompt, priority, max_cost, humanize, stream, models_yaml):
    """Route PROMPT to the best available model and print the response."""
    from ijachi_router.core import Router
    from ijachi_router.streaming import stream_route

    try:
        router = Router(models_yaml=models_yaml)
        if priority:
            router.config.priority = priority
        if max_cost is not None:
            router.config.max_cost_per_call = max_cost

        if stream:
            for chunk in stream_route(prompt, priority=priority, humanize_mode=humanize):
                click.echo(chunk, nl=False)
            click.echo()
            return

        res = router.route(prompt, humanize_mode=humanize)

        # Print output text
        click.echo(res.text)
        click.echo()

        # Print cost / latency footer in subtle gray/dim style
        footer = (
            f"[model={res.model:<24} "
            f"cost=${res.cost_usd:.4f}  "
            f"latency={res.latency_s:.2f}s  "
            f"tokens={res.input_tokens}in/{res.output_tokens}out  "
            f"humanize={humanize}]"
        )
        click.echo(click.style(footer, fg="bright_black"))

    except Exception as e:  # noqa: BLE001
        raise click.ClickException(str(e)) from e


@main.command()
def stats():
    """Show spend and latency table for all recorded calls."""
    from ijachi_router.metrics import print_stats
    print_stats()


@main.command(name="providers")
@click.option("--models-yaml", default=None, hidden=True)
def providers(models_yaml):
    """List providers and their configuration status."""
    import os
    from ijachi_router.config import load_config, _PROVIDER_ENV_KEYS

    config = load_config(models_yaml)
    click.echo("\nProvider status:\n")

    listed = {m.provider for m in config.models}
    for provider in sorted(listed):
        env_key = _PROVIDER_ENV_KEYS.get(provider)
        if env_key is None:
            status = click.style("✓ available (no key required)", fg="green")
        elif os.environ.get(env_key):
            status = click.style(f"✓ configured ({env_key} set)", fg="green")
        else:
            status = click.style(f"✗ not configured ({env_key} not set)", fg="red")
        click.echo(f"  {provider:<15} {status}")

    click.echo()
    click.echo(
        f"Active providers: "
        f"{', '.join(sorted(config.available_providers)) or 'none (set an API key)'}"
    )
    click.echo()


@main.command(name="update-catalog")
@click.option("--force", is_flag=True, help="Force refresh from remote registry.")
def update_catalog_cmd(force):
    """Fetch the latest model catalog & pricing rates from remote registries."""
    from ijachi_router.catalog_updater import update_catalog

    click.echo("Fetching dynamic model catalog & pricing updates...")
    ok, msg = update_catalog(force=force)
    if ok:
        click.echo(click.style(f"✓ {msg}", fg="green"))
    else:
        click.echo(click.style(f"✗ {msg}", fg="red"))


@main.command()
def train():
    """Retrain the prompt classifier from data/train_data.csv."""
    from ijachi_router.classifier import retrain
    click.echo("Training classifier from data/train_data.csv …")
    try:
        retrain()
        click.echo(
            click.style(
                "✓ Classifier trained and cached to ~/.ijachi-llmr/classifier.pkl",
                fg="green",
            )
        )
    except Exception as e:  # noqa: BLE001
        raise click.ClickException(str(e)) from e


@main.command(name="agent")
@click.argument("task")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
@click.option("--model", "-m", default=None, help="Force a specific model (e.g. gpt-4o, claude-3-5-sonnet).")
@click.option("--max-steps", "-s", type=int, default=10, help="Maximum tool iteration steps.")
@click.option("--no-approval", is_flag=True, help="Auto-approve file changes and shell commands.")
@click.option("--style", default=None, help="Code style guide (pep8, black, google, prettier, airbnb).")
@click.option("--accessibility", "-a", is_flag=True, help="Screen-reader accessibility mode.")
def agent_cmd(task, priority, model, max_steps, no_approval, style, accessibility):
    """[AGENTIC] Run an autonomous workspace file editing task."""
    from ijachi_router.agent import AgenticRouter
    from ijachi_router.config import load_config

    cfg = load_config()
    style_guide = style or cfg.style_guide
    acc = accessibility or cfg.accessibility

    agent = AgenticRouter(
        priority=priority,
        require_approval=not no_approval,
        style_guide=style_guide,
        auto_format=cfg.auto_format,
        require_comments=cfg.require_comments,
        accessible=acc,
        force_model=model,
    )
    if acc:
        print(f"ijachi: Starting autonomous task: {task}")
    else:
        model_str = f" [model: {model}]" if model else f" [priority: {priority}]"
        click.echo(click.style(f"🚀 Starting autonomous agentic workspace task{model_str}: {task}", fg="cyan"))
    result = agent.run(task, max_steps=max_steps)
    click.echo("\n" + click.style("=== Task Result ===", fg="green", bold=True))
    click.echo(result.final_text)
    click.echo(click.style(f"\n[steps={len(result.steps)} total_cost=${result.total_cost_usd:.4f}]", fg="bright_black"))


@main.command(name="chat")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
@click.option("--model", "-m", default=None, help="Force a specific model (e.g. gpt-4o, claude-3-5-sonnet).")
@click.option("--style", default=None, help="Code style guide (pep8, black, google, prettier, airbnb).")
@click.option("--accessibility", "-a", is_flag=True, help="Screen-reader accessibility mode (sequential labeled output).")
@click.option("--theme", default=None, help="UI theme: dark, light, ansi, accessible, auto.")
@click.option("--vim", is_flag=True, default=False, help="Enable Vim editing mode in the prompt.")
def chat_cmd(priority, model, style, accessibility, theme, vim):
    """[AGENTIC] Start an interactive terminal REPL chat session with workspace tools."""
    from ijachi_router.agent import AgenticRouter
    from ijachi_router.config import load_config
    from ijachi_router.providers.base import ProviderError
    from ijachi_router.transcript import Transcript
    from ijachi_router.ui import set_theme, cycle_permission_mode, print_welcome_card
    from ijachi_router.skill_manager import SkillManager
    from ijachi_router.toasts import toast_manager

    # Load persisted config and apply CLI overrides
    cfg = load_config()
    style_guide = style or cfg.style_guide
    acc = accessibility or cfg.accessibility
    active_theme = theme or cfg.theme
    vim_mode = vim or cfg.vim_mode

    # Permission mode (cycled with /mode or Shift+Tab)
    permission_mode = "manual"
    accept_edits_on = False

    # Apply theme
    applied_theme = set_theme(active_theme)

    # Reload saved API keys
    try:
        from ijachi_router.key_manager import KeyManager
        KeyManager().load_keys_into_env()
    except Exception:
        pass

    agent = AgenticRouter(
        priority=priority,
        require_approval=True,
        style_guide=style_guide,
        auto_format=cfg.auto_format,
        require_comments=cfg.require_comments,
        accessible=acc,
        force_model=model,
        permission_mode=permission_mode,
    )

    # Session transcript
    transcript = Transcript(session_id="chat")

    # Skill manager for '/skills' slash command
    skill_manager = SkillManager(workspace_root=agent.tools.root_dir)

    # Conversation turn counters for the status bar
    history_index = 0
    history_total = 0

    # Prompt engine callbacks
    def _open_transcript():
        transcript.view()

    def _toggle_checklist():
        agent.checklist.render()

    def _rewind():
        click.echo(click.style("\n⏪ Rewind: no checkpoint available in this session.", fg="yellow"))

    # Build PromptEngine (falls back to input() if prompt_toolkit not installed)
    try:
        from ijachi_router.prompt_engine import PromptEngine
        engine = PromptEngine(
            workspace_root=agent.tools.root_dir,
            model=model or f"auto ({priority})",
            vim_mode=vim_mode,
            permission_mode=permission_mode,
            on_transcript_open=_open_transcript,
            on_checklist_toggle=_toggle_checklist,
            on_rewind=_rewind,
            skill_names=[s.name for s in skill_manager.list_skills()],
        )
    except Exception:
        engine = None  # Fallback to plain input()

    # Session header / welcome card
    if acc:
        print("ijachi: Interactive session started. Type 'exit' to quit.")
    else:
        print_welcome_card(
            model=model or f"auto ({priority})",
            billing="API Usage Billing",
            workspace=str(agent.tools.root_dir),
        )

    session_cost = 0.0

    while True:
        try:
            # Prepare live state for the status bar
            agent_count = agent.background.active_count() if agent.background else 0
            toast_badge = toast_manager.render_badge()

            # Get input via PromptEngine or plain input()
            if engine:
                user_input = engine.prompt(
                    "ijachi-code> ",
                    cost_usd=session_cost,
                    history_index=history_index,
                    history_total=history_total,
                    agent_count=agent_count,
                    toast_badge=toast_badge,
                    accept_edits_on=accept_edits_on,
                )
                if user_input is None:
                    # None = Ctrl+C or shell command handled inline
                    continue
                # Expand any pasted text placeholders
                user_input = engine.resolve_pastes(user_input)
            else:
                try:
                    user_input = input("ijachi-code> ")
                except (KeyboardInterrupt, EOFError):
                    user_input = None

            if user_input is None:
                if acc:
                    print("ijachi: Session ended.")
                else:
                    click.echo(click.style("\n👋 Session ended.", fg="cyan"))
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            # exit/quit
            if stripped.lower() in {"exit", "quit", "q", ":q"}:
                if acc:
                    print("ijachi: Goodbye! Session ended.")
                else:
                    click.echo(click.style("👋 Goodbye! Session ended.", fg="cyan"))
                break

            # --- Slash command handling ---
            if stripped.startswith("/"):
                parts = stripped[1:].split(None, 1)
                cmd = parts[0].lower() if parts else ""
                arg = parts[1] if len(parts) > 1 else ""

                if cmd in ("model", "models"):
                    if not arg or arg in ("list", "ls"):
                        # Show available models
                        click.echo(click.style("\n🤖 Available Models & Providers:", fg="cyan", bold=True))
                        current_status = agent.force_model or f"auto ({agent.priority})"
                        click.echo(f"  Current Active: {current_status}\n")
                        for m in cfg.available_models():
                            click.echo(f"  • {m.model_id:<32} [{m.provider}] in:${m.input_per_1k}/1k out:${m.output_per_1k}/1k tags={','.join(m.tags[:3])}")
                        click.echo("\n  Usage: /model <model_name> (e.g. /model gpt-4o) or /model auto\n")
                    elif arg.lower() in ("auto", "default", "reset"):
                        agent.set_model(None)
                        if engine:
                            engine.model = f"auto ({agent.priority})"
                        click.echo(click.style(f"✓ Model reset to dynamic auto-routing ({agent.priority}).", fg="green"))
                    else:
                        agent.set_model(arg)
                        if engine:
                            engine.model = arg
                        click.echo(click.style(f"✓ Model switched to '{arg}'.", fg="green"))

                elif cmd in ("priority", "p"):
                    if arg.lower() in ("cost", "speed", "quality", "balanced"):
                        agent.set_priority(arg.lower())
                        if engine:
                            engine.model = f"auto ({arg.lower()})"
                        click.echo(click.style(f"✓ Routing priority set to '{arg.lower()}'.", fg="green"))
                    else:
                        click.echo("Usage: /priority <cost|speed|quality|balanced>")

                elif cmd == "theme":
                    from ijachi_router.ui import set_theme, list_themes
                    if arg in list_themes() or arg == "auto":
                        applied = set_theme(arg)
                        click.echo(click.style(f"✓ Theme set to '{applied}'.", fg="green"))
                    else:
                        click.echo(f"Available themes: {', '.join(list_themes())}")

                elif cmd == "tasks":
                    agent.checklist.render()

                elif cmd in ("skills", "skill"):
                    skill_manager.print_skills_table()

                elif cmd == "config":
                    cfg_parts = arg.split(None, 1)
                    if len(cfg_parts) == 2:
                        _handle_config_set(cfg_parts[0], cfg_parts[1])
                    else:
                        _print_config(cfg)

                elif cmd in ("help", "?"):
                    from ijachi_router.prompt_engine import _HELP_TEXT
                    print(_HELP_TEXT)

                elif cmd in ("memory", "mem"):
                    subparts = arg.split(None, 1)
                    subcmd = subparts[0].lower() if subparts else ""
                    subarg = subparts[1] if len(subparts) > 1 else ""

                    if not subcmd or subcmd == "summary":
                        click.echo(click.style(agent.ctx.summary(), fg="cyan"))
                    elif subcmd in ("view", "context", "block"):
                        ctx_block = agent.ctx.build_context_block()
                        if ctx_block:
                            click.echo(click.style(f"\n{ctx_block}\n", fg="bright_black"))
                        else:
                            click.echo(click.style("Context memory is currently empty for this project.", fg="yellow"))
                    elif subcmd == "clear":
                        agent.ctx.clear()
                        click.echo(click.style("✓ Context memory reset (L1 disk, L2 session, L3 tasks cleared).", fg="green"))
                    elif subcmd == "goal":
                        if subarg:
                            agent.ctx.set_session_goal(subarg)
                            click.echo(click.style(f"✓ Session goal updated to: '{subarg}'", fg="green"))
                        else:
                            curr_goal = agent.ctx.session_goal or "(none set)"
                            click.echo(click.style(f"Current session goal: {curr_goal}\nUsage: /memory goal <goal description>", fg="yellow"))
                    elif subcmd in ("decision", "decide"):
                        if subarg:
                            agent.ctx.l1_global.add_architectural_decision(subarg)
                            click.echo(click.style(f"✓ Architectural decision recorded: '{subarg}'", fg="green"))
                        else:
                            click.echo("Usage: /memory decide <architectural decision>")
                    else:
                        click.echo("Usage: /memory [summary | view | goal <text> | decide <text> | clear]")

                elif cmd == "mode":
                    permission_mode = cycle_permission_mode(permission_mode)
                    agent.set_permission_mode(permission_mode)
                    if engine:
                        engine.set_permission_mode(permission_mode)
                    from ijachi_router.ui import get_permission_mode_label
                    click.echo(click.style(
                        f"✓ Permission mode: {get_permission_mode_label(permission_mode)}",
                        fg="cyan",
                    ))

                elif cmd == "init":
                    try:
                        claude_md_path = agent.planner.generate_claude_md()
                        click.echo(click.style(f"✓ Generated {claude_md_path}", fg="green"))
                    except Exception as exc:
                        click.echo(click.style(f"✗ Could not generate CLAUDE.md: {exc}", fg="red"))

                else:
                    click.echo(click.style(f"Unknown command: /{cmd}. Type /help for commands.", fg="yellow"))
                continue
            # --- End slash commands ---

            # Record user turn in transcript
            transcript.add_user_turn(stripped)

            result = agent.run(stripped)
            session_cost += result.total_cost_usd

            if engine:
                engine.update_cost(result.total_cost_usd)

            # Update conversation turn counters
            history_total += 1
            history_index = history_total

            # Accept-edits mode is enabled in accept-edits/auto modes (toolbar indicator)
            accept_edits_on = permission_mode in {"accept-edits", "auto"}

            # Record assistant turn in transcript (with telemetry summary)
            from ijachi_router.telemetry import telemetry
            telemetry_summary = telemetry.format_status_line()
            transcript.add_assistant_turn(
                content=result.final_text,
                model=result.steps[-1].model_used if result.steps else "",
                provider=result.steps[-1].provider if result.steps else "",
                cost_usd=result.total_cost_usd,
                telemetry_summary=telemetry_summary,
            )

            if acc:
                print(f"ijachi: {result.final_text}")
            else:
                click.echo("\n" + result.final_text + "\n")

        except ProviderError as exc:
            if acc:
                print(f"tool_error: Provider error: {exc}")
            else:
                click.echo(click.style(f"\n✗ Provider error: {exc}", fg="red"))
                click.echo(click.style(
                    "  Tip: Run 'ijachi keys set <provider> <key>' to configure a provider,\n"
                    "  or 'ijachi providers' to check which providers are currently active.",
                    fg="yellow",
                ))
        except (KeyboardInterrupt, EOFError):
            if acc:
                print("ijachi: Session ended.")
            else:
                click.echo(click.style("\n👋 Session ended.", fg="cyan"))
            break
        except Exception as exc:  # noqa: BLE001
            if acc:
                print(f"tool_error: Unexpected error: {exc}")
            else:
                click.echo(click.style(f"\n✗ Unexpected error: {exc}", fg="red"))
                click.echo(click.style("  Type 'exit' to quit or try a different prompt.", fg="yellow"))

    # Auto-save transcript on exit
    try:
        saved = transcript.save()
        if not acc:
            click.echo(click.style(f"[Transcript saved to {saved}]", fg="bright_black"))
    except Exception:
        pass


def _handle_config_set(key: str, value: str) -> None:
    """Persist a config key-value pair to ~/.ijachi-llmr/config.yaml.

    Args:
        key: Config key name (e.g. 'style_guide', 'theme', 'vim_mode').
        value: String value to set.
    """
    import yaml
    from pathlib import Path
    config_path = Path.home() / ".ijachi-llmr" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if config_path.exists():
        try:
            with config_path.open() as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            pass
    # Coerce booleans
    if value.lower() in ("true", "1", "yes"):
        data[key] = True
    elif value.lower() in ("false", "0", "no"):
        data[key] = False
    else:
        data[key] = value
    with config_path.open("w") as f:
        yaml.safe_dump(data, f)
    click.echo(click.style(f"✓ Config: {key} = {data[key]} (saved to {config_path})", fg="green"))


def _print_config(cfg) -> None:
    """Print current config values to the console.

    Args:
        cfg: RouterConfig instance to display.
    """
    click.echo(click.style("\n⚙️  Current Config:", fg="cyan", bold=True))
    click.echo(f"  priority        = {cfg.priority}")
    click.echo(f"  style_guide     = {cfg.style_guide}")
    click.echo(f"  auto_format     = {cfg.auto_format}")
    click.echo(f"  require_comments= {cfg.require_comments}")
    click.echo(f"  vim_mode        = {cfg.vim_mode}")
    click.echo(f"  theme           = {cfg.theme}")
    click.echo(f"  accessibility   = {cfg.accessibility}")
    click.echo(f"  max_cost        = {cfg.max_cost_per_call}")
    click.echo()


@main.command(name="fix")
@click.option("--command", "-c", default="pytest", help="Test runner command (pytest, npm test, etc.).")
@click.option("--max-retries", "-r", default=3, type=int, help="Maximum repair retry iterations.")
def fix_cmd(command, max_retries):
    """[KILLER FEATURE] Run automated test repair loop until 100% passing."""
    from ijachi_router.agent import AgenticRouter

    agent = AgenticRouter(require_approval=False)
    res = agent.fix_tests(test_command=command, max_retries=max_retries)
    click.echo(res.final_text)


@main.command(name="commit")
@click.option("--message", "-m", default=None, help="Commit message override.")
def commit_cmd(message):
    """[KILLER FEATURE] Generate Conventional Commit message and commit changes."""
    from ijachi_router.agent import AgenticRouter

    agent = AgenticRouter(require_approval=True)
    res = agent.git_commit(message=message)
    click.echo(click.style(res, fg="green"))


@main.command(name="index")
def index_cmd():
    """[KILLER FEATURE] Scan and index workspace code symbols into symbols.json cache."""
    from ijachi_router.indexer import WorkspaceIndexer

    indexer = WorkspaceIndexer()
    symbols = indexer.index_workspace()
    click.echo(click.style(f"✓ Indexed {len(symbols)} workspace symbols.", fg="green"))
    click.echo(indexer.get_summary())


@main.group(name="memory")
def memory_group():
    """[MEMORY] Manage persistent project memory & token savings."""


@memory_group.command(name="status")
@click.option("--session-id", default="default", help="Session ID to inspect.")
def memory_status_cmd(session_id):
    """View project memory status, active turns, and token savings."""
    from ijachi_router.memory import ProjectMemory

    mem = ProjectMemory(session_id=session_id)
    click.echo(click.style(mem.summary(), fg="cyan"))


@memory_group.command(name="clear")
@click.option("--session-id", default="default", help="Session ID to clear.")
def memory_clear_cmd(session_id):
    """Clear persistent project session memory."""
    from ijachi_router.memory import ProjectMemory

    mem = ProjectMemory(session_id=session_id)
    mem.clear()
    click.echo(click.style(f"✓ Cleared memory for session '{session_id}'.", fg="yellow"))


@main.command(name="benchmark")
@click.option("--category", "-c", type=click.Choice(["code", "reasoning", "speed"]), default="code")
def benchmark_cmd(category):
    """[NEXT-GEN] Run standardized performance benchmark across active providers."""
    from ijachi_router.benchmarker import BenchmarkEngine

    click.echo(click.style(f"📊 Running model performance benchmark (category: {category})...", fg="cyan"))
    engine = BenchmarkEngine()
    results = engine.run_benchmark(prompt_category=category)
    click.echo(engine.format_table(results))


@main.command(name="swarm")
@click.argument("goal")
def swarm_cmd(goal):
    """[NEXT-GEN] Coordinate 4 sub-agents (Architect, Dev, Security, QA) on a feature goal."""
    from ijachi_router.swarm import SwarmManager

    click.echo(click.style(f"🐝 Launching Multi-Agent Coding Swarm: '{goal}'", fg="cyan"))
    manager = SwarmManager()
    res = manager.run_swarm(feature_goal=goal)
    for phase in res.phases:
        click.echo("\n" + click.style(f"=== {phase.agent_name} ({phase.model_used}) ===", fg="yellow", bold=True))
        click.echo(phase.output_text[:1500])
    click.echo(click.style(f"\n[swarm_phases={len(res.phases)} total_cost=${res.total_cost_usd:.4f}]", fg="bright_black"))


@main.command(name="consensus")
@click.argument("prompt")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="quality")
def consensus_cmd(prompt, priority):
    """[NEXT-GEN] Multi-model peer-review consensus synthesis."""
    from ijachi_router.consensus import consensus_route

    click.echo(click.style("🧠 Running multi-model consensus peer review...", fg="cyan"))
    res = consensus_route(prompt=prompt, priority=priority)
    click.echo("\n" + click.style(f"=== Consensus Output ({res.consensus_model}) ===", fg="green", bold=True))
    click.echo(res.final_text)
    click.echo(click.style(f"\n[models={res.model_a} & {res.model_b} cost=${res.total_cost_usd:.4f}]", fg="bright_black"))


@main.command(name="doc")
def doc_cmd():
    """[NEXT-GEN] Auto-generate ARCHITECTURE.md with interactive Mermaid diagrams."""
    from ijachi_router.docgen import DocGenerator

    docgen = DocGenerator()
    msg = docgen.generate_architecture_md()
    click.echo(click.style(f"✓ {msg}", fg="green"))


@main.command(name="pr-review")
@click.argument("pr_number")
def pr_review_cmd(pr_number):
    """[ECOSYSTEM] Perform automated architectural code review on GitHub PR."""
    from ijachi_router.github_automation import GitHubAutomation

    click.echo(click.style(f"🤖 Reviewing Pull Request #{pr_number}...", fg="cyan"))
    gh_auto = GitHubAutomation()
    review = gh_auto.review_pr(pr_number)
    click.echo(review)


@main.command(name="release")
@click.argument("tag")
def release_cmd(tag):
    """[ECOSYSTEM] Auto-generate CHANGELOG.md release notes for a Git tag."""
    from ijachi_router.github_automation import GitHubAutomation

    gh_auto = GitHubAutomation()
    msg = gh_auto.generate_release_notes(tag)
    click.echo(click.style(f"✓ {msg}", fg="green"))


@main.group(name="budget")
def budget_group():
    """[ECOSYSTEM] Manage monthly USD budget limits & failover caps."""


@budget_group.command(name="status")
def budget_status_cmd():
    """View monthly budget limits and current spend status."""
    from ijachi_router.budget import BudgetManager

    bm = BudgetManager()
    click.echo(click.style(bm.summary(), fg="cyan"))


@budget_group.command(name="set")
@click.argument("limit_usd", type=float)
def budget_set_cmd(limit_usd):
    """Set monthly USD budget limit."""
    from ijachi_router.budget import BudgetManager

    bm = BudgetManager()
    bm.set_budget(limit_usd)
    click.echo(click.style(f"✓ Monthly budget limit set to ${limit_usd:.2f} USD.", fg="green"))


@main.command(name="export-sdk")
@click.option("--lang", "-l", type=click.Choice(["typescript", "go", "rust"]), default="typescript")
def export_sdk_cmd(lang):
    """[ECOSYSTEM] Export native client SDK library (TypeScript, Go, Rust)."""
    from ijachi_router.sdk_generator import SDKGenerator

    generator = SDKGenerator()
    msg = generator.export_sdk(language=lang)
    click.echo(click.style(f"✓ {msg}", fg="green"))


@main.group(name="models")
def models_group():
    """[MODELS] Manage LLM model candidate definitions & pricing."""


@models_group.command(name="list")
def models_list_cmd():
    """List all configured candidate models and their status."""
    from ijachi_router.model_manager import ModelManager

    mm = ModelManager()
    models = mm.list_models()
    click.echo(click.style(f"\n{'Model ID':<30} {'Provider':<15} {'Speed':<10} {'Status':<10} {'In/1k($)':<10} {'Out/1k($)':<10}", fg="cyan", bold=True))
    click.echo("-" * 90)
    for m in models:
        status = "disabled" if "disabled" in m.tags else "enabled"
        click.echo(f"{m.model_id:<30} {m.provider:<15} {m.speed_tier:<10} {status:<10} ${m.input_per_1k:<9.4f} ${m.output_per_1k:<9.4f}")
    click.echo()


@models_group.command(name="add")
@click.argument("model_id")
@click.argument("provider")
@click.option("--speed", type=click.Choice(["fast", "medium", "slow"]), default="medium")
@click.option("--input-cost", type=float, default=0.001)
@click.option("--output-cost", type=float, default=0.002)
def models_add_cmd(model_id, provider, speed, input_cost, output_cost):
    """Add a new custom model to models.yaml."""
    from ijachi_router.model_manager import ModelManager

    mm = ModelManager()
    msg = mm.add_model(model_id=model_id, provider=provider, speed_tier=speed, input_per_1k=input_cost, output_per_1k=output_cost)
    click.echo(click.style(f"✓ {msg}", fg="green"))


@models_group.command(name="toggle")
@click.argument("model_id")
def models_toggle_cmd(model_id):
    """Enable or disable a model in models.yaml."""
    from ijachi_router.model_manager import ModelManager

    mm = ModelManager()
    msg = mm.toggle_model(model_id=model_id)
    if "not found" in msg:
        click.echo(click.style(msg, fg="yellow"))
    else:
        click.echo(click.style(f"✓ {msg}", fg="green"))


@main.group(name="keys")
def keys_group():
    """[KEYS] Manage provider API keys securely."""


@keys_group.command(name="list")
def keys_list_cmd():
    """List configured provider API keys (masked)."""
    from ijachi_router.key_manager import KeyManager

    km = KeyManager()
    keys = km.list_keys()
    if not keys:
        click.echo(click.style("No provider API keys configured yet. Set one with: ijachi-router keys set <provider> <key>", fg="yellow"))
        return
    click.echo(click.style("\nConfigured Provider API Keys:", fg="cyan", bold=True))
    for p, masked in keys.items():
        click.echo(f"  • {p:<15} -> {masked}")
    click.echo()


@keys_group.command(name="set")
@click.argument("provider")
@click.argument("key_value")
def keys_set_cmd(provider, key_value):
    """Set and save an API key for a provider."""
    from ijachi_router.key_manager import KeyManager

    km = KeyManager()
    msg = km.set_key(provider=provider, key_value=key_value)
    click.echo(click.style(f"✓ {msg}", fg="green"))


@keys_group.command(name="clear")
@click.argument("provider")
def keys_clear_cmd(provider):
    """Clear an API key for a provider."""
    from ijachi_router.key_manager import KeyManager

    km = KeyManager()
    msg = km.clear_key(provider=provider)
    click.echo(click.style(f"✓ {msg}", fg="yellow"))


@keys_group.command(name="test")
def keys_test_cmd():
    """Test live connectivity for configured provider API keys."""
    from ijachi_router.key_manager import KeyManager

    km = KeyManager()
    status = km.test_keys()
    click.echo(click.style("\nProvider Key Verification:", fg="cyan", bold=True))
    for p, ok in status.items():
        icon = "✓ Active" if ok else "✗ Failed"
        click.echo(f"  • {p:<15} -> {icon}")
    click.echo()




@main.command()
@click.option("--host", default="127.0.0.1", help="Host address to bind.")
@click.option("--port", default=8000, type=int, help="Port to bind REST API server.")
@click.option("--license-key", default=None, help="Pro license key.")
def serve(host, port, license_key):
    """[PRO] Launch the REST API Gateway & Web Telemetry Dashboard server."""
    from ijachi_router.license import set_license_key
    from ijachi_router.server import start_server

    if license_key:
        set_license_key(license_key)

    server = start_server(host=host, port=port)
    if server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\nServer stopped.")


@main.command()
@click.option("--host", default="127.0.0.1", help="Host address to bind.")
@click.option("--port", default=8000, type=int, help="Port to bind dashboard.")
def dashboard(host, port):
    """Open the Web Telemetry Dashboard in your default browser."""
    import threading
    import webbrowser
    from ijachi_router.server import start_server

    url = f"http://{host}:{port}/"
    server = start_server(host=host, port=port)

    # Open browser shortly after the server starts listening
    def _open_browser():
        import time
        time.sleep(0.5)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()
    click.echo(f"Opening Web Dashboard at {url} …")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nDashboard server stopped.")


@main.command(name="extension-server")
@click.option("--host", default="127.0.0.1", help="Host address to bind.")
@click.option("--port", default=8001, type=int, help="Port to bind the IDE extension server.")
def extension_server_cmd(host, port):
    """[PRO] Start JSON-RPC/REST bridge server for IDE extensions."""
    from ijachi_router.lsp import start_lsp_server

    click.echo(click.style(f"🔌 Starting IDE extension server on http://{host}:{port} ...", fg="cyan"))
    server = start_lsp_server(host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nExtension server stopped.")


@main.group()
def license():
    """Manage ijachi-llm-router Pro license keys."""


@license.command(name="set")
@click.argument("key")
def license_set(key):
    """Set and activate a Pro license key."""
    from ijachi_router.license import set_license_key

    ok, msg = set_license_key(key)
    if ok:
        click.echo(click.style(f"✓ {msg}", fg="green"))
    else:
        click.echo(click.style(f"✗ {msg}", fg="red"))


@license.command(name="status")
def license_status():
    """Check current license status."""
    from ijachi_router.license import get_license_key, validate_license_key

    key = get_license_key()
    valid, msg = validate_license_key(key)
    if valid:
        click.echo(click.style(f"✓ Pro License Active (Key: {key[:8]}...)", fg="green"))
    else:
        click.echo(click.style(f"ℹ Free Tier / Community Edition ({msg})", fg="yellow"))
        click.echo("👉 Upgrade to Pro on Paystack: https://paystack.shop/pay/enlqpvzflw")


@license.command(name="remove")
def license_remove():
    """Remove local Pro license key."""
    from ijachi_router.license import remove_license_key

    remove_license_key()
    click.echo(click.style("✓ License key removed. Reset to Free Tier.", fg="yellow"))


@main.command(name="update")
def update_cmd():
    """[UPDATE] Auto-update ijachi to the latest version."""
    from ijachi_router.updater import update_ijachi

    msg = update_ijachi()
    click.echo(click.style(f"✓ {msg}", fg="green", bold=True))


@main.group(name="skills")
def skills_group():
    """[SKILLS] Discover, list, run, and install ijachi-code skills."""


@skills_group.command(name="list")
def skills_list_cmd():
    """List all discovered skills (builtin + global + workspace-local)."""
    from ijachi_router.skill_manager import SkillManager
    SkillManager().print_skills_table()


@skills_group.command(name="run")
@click.argument("skill_name")
@click.argument("task")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
def skills_run_cmd(skill_name, task, priority):
    """Run a specific skill by NAME on TASK."""
    from ijachi_router.skill_manager import SkillManager
    from ijachi_router.agent import AgenticRouter

    sm = SkillManager()
    skill = sm.get_skill(skill_name)
    if not skill:
        click.echo(click.style(f"✗ Skill '{skill_name}' not found. Run 'ijachi-router skills list' to see available skills.", fg="red"))
        return

    click.echo(click.style(f"⚡ Running skill: [bold]{skill.name}[/bold] v{skill.version}", fg="cyan"))
    click.echo(click.style(f"   {skill.description}", fg="bright_black"))

    agent = AgenticRouter(priority=priority, require_approval=True)
    # Prepend skill instructions to the task
    enriched_task = f"{skill.instructions}\n\nTask: {task}"
    result = agent.run(enriched_task)
    click.echo("\n" + click.style("=== Skill Result ===", fg="green", bold=True))
    click.echo(result.final_text)
    click.echo(click.style(f"\n[skill={skill.name} steps={len(result.steps)} cost=${result.total_cost_usd:.4f}]", fg="bright_black"))


@skills_group.command(name="add")
@click.argument("path", type=click.Path(exists=True))
def skills_add_cmd(path):
    """Install a skill directory into the global skills root (~/.ijachi-llmr/skills/)."""
    from ijachi_router.skill_manager import SkillManager
    from pathlib import Path

    sm = SkillManager()
    msg = sm.install_skill(Path(path))
    if msg.startswith("✓"):
        click.echo(click.style(msg, fg="green"))
    else:
        click.echo(click.style(msg, fg="red"))


@main.command(name="theme")
@click.argument("theme_name", type=click.Choice(["dark", "light", "ansi", "accessible", "auto"]), required=False)
def theme_cmd(theme_name):
    """Switch or display the active UI theme (dark/light/ansi/accessible/auto)."""
    from ijachi_router.ui import set_theme, get_current_theme, list_themes

    if not theme_name:
        current = get_current_theme()
        click.echo(f"Current theme: [bold]{current}[/bold]")
        click.echo(f"Available: {', '.join(list_themes())}")
        return

    applied = set_theme(theme_name)
    _handle_config_set("theme", applied)
    click.echo(click.style(f"✓ Theme switched to '{applied}' and saved.", fg="green"))


def code_main():
    """Standalone ijachi-code CLI entrypoint tuned specifically for coding tasks."""
    import sys
    known_commands = {
        "route", "stats", "providers", "provider", "update-catalog", "train",
        "serve", "dashboard", "license", "setup", "launcher", "export-sdk",
        "models", "keys", "agent", "chat", "swarm", "fix", "consensus",
        "index", "doc", "commit", "benchmark", "budget", "extension-server",
        "update", "skills", "theme",
    }
    args = sys.argv[1:]
    if args and not args[0].startswith("-") and args[0] not in known_commands:
        sys.argv.insert(1, "route")
        if "--priority" not in sys.argv and "-p" not in sys.argv:
            sys.argv.extend(["--priority", "quality"])
    main()


if __name__ == "__main__":
    main()
