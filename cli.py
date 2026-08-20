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
        wizard = LauncherWizard()
        wizard.run_interactive_setup()


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
@click.option("--max-steps", "-s", type=int, default=10, help="Maximum tool iteration steps.")
@click.option("--no-approval", is_flag=True, help="Auto-approve file changes and shell commands.")
def agent_cmd(task, priority, max_steps, no_approval):
    """[AGENTIC] Run an autonomous workspace file editing task."""
    from ijachi_router.agent import AgenticRouter

    agent = AgenticRouter(priority=priority, require_approval=not no_approval)
    click.echo(click.style(f"🚀 Starting autonomous agentic workspace task: {task}", fg="cyan"))
    result = agent.run(task, max_steps=max_steps)
    click.echo("\n" + click.style("=== Task Result ===", fg="green", bold=True))
    click.echo(result.final_text)
    click.echo(click.style(f"\n[steps={len(result.steps)} total_cost=${result.total_cost_usd:.4f}]", fg="bright_black"))


@main.command(name="chat")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
def chat_cmd(priority):
    """[AGENTIC] Start an interactive terminal REPL chat session with workspace tools."""
    from ijachi_router.agent import AgenticRouter

    agent = AgenticRouter(priority=priority, require_approval=True)
    click.echo(click.style("💬 ijachi-code Interactive Agentic REPL Session", fg="cyan", bold=True))
    click.echo("Type your workspace coding prompt or 'exit' / 'quit' to end.\n")

    while True:
        try:
            user_input = click.prompt("ijachi-code>", type=str)
            if user_input.strip().lower() in {"exit", "quit", "q"}:
                click.echo("Goodbye!")
                break
            result = agent.run(user_input)
            click.echo("\n" + result.final_text + "\n")
        except (KeyboardInterrupt, EOFError):
            click.echo("\nSession ended.")
            break


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
    click.echo(click.style(f"\n{'Model ID':<30} {'Provider':<15} {'Speed':<10} {'In/1k($)':<10} {'Out/1k($)':<10}", fg="cyan", bold=True))
    click.echo("-" * 80)
    for m in models:
        click.echo(f"{m.model_id:<30} {m.provider:<15} {m.speed_tier:<10} ${m.input_per_1k:<9.4f} ${m.output_per_1k:<9.4f}")
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
        icon = "✓ Active" if ok else "✗ Missing"
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
    """[PRO] Open the Web Telemetry Dashboard in your default browser."""
    import webbrowser
    from ijachi_router.license import check_pro_access

    if not check_pro_access("Web Telemetry Dashboard"):
        return

    url = f"http://{host}:{port}/"
    click.echo(f"Opening Web Dashboard at {url} …")
    webbrowser.open(url)


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


def code_main():
    """Standalone ijachi-code CLI entrypoint tuned specifically for coding tasks."""
    import sys
    known_commands = {
        "route", "stats", "providers", "provider", "update-catalog", "train",
        "serve", "dashboard", "license", "setup", "launcher", "export-sdk",
        "models", "keys", "agent", "chat", "swarm", "fix", "consensus",
        "index", "doc", "commit", "benchmark", "budget", "extension-server"
    }
    args = sys.argv[1:]
    if args and not args[0].startswith("-") and args[0] not in known_commands:
        sys.argv.insert(1, "route")
        if "--priority" not in sys.argv and "-p" not in sys.argv:
            sys.argv.extend(["--priority", "quality"])
    main()


if __name__ == "__main__":
    main()
