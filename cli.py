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


@click.group(cls=RouterCLI)
def main():
    """ijachi-llm-router: one prompt, best model, automatic fallback.

    \b
    Quick start:
      export ANTHROPIC_API_KEY=sk-...
      ijachi-router route "Explain quicksort in Python"
    """


@main.command(name="route")
@click.argument("prompt")
@click.option("--priority", "-p",
              type=click.Choice(["cost", "speed", "quality", "balanced"]),
              default=None,
              help="Override routing priority for this call.")
@click.option("--max-cost", "-m", type=float, default=None,
              help="Max USD per call (skips models that exceed this).")
@click.option("--models-yaml", default=None, hidden=True,
              help="Custom path to models.yaml.")
def route_cmd(prompt, priority, max_cost, models_yaml):
    """Route PROMPT to the best available model and print the response."""
    from ijachi_router.core import Router

    try:
        router = Router(models_yaml=models_yaml)
        if priority:
            router.config.priority = priority
        if max_cost is not None:
            router.config.max_cost_per_call = max_cost

        res = router.route(prompt)

        # Print output text
        click.echo(res.text)
        click.echo()

        # Print cost / latency footer in subtle gray/dim style
        footer = (
            f"[model={res.model_used:<24} "
            f"cost=${res.cost:.4f}  "
            f"latency={res.latency_sec:.2f}s  "
            f"tokens={res.input_tokens}in/{res.output_tokens}out]"
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


@main.command(name="banner")
def banner_cmd():
    """Display bold ASCII art banner for IJACHI."""
    from ijachi_router.ui import print_banner

    print_banner()


@main.command(name="chat")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="balanced")
@click.option("--plan", is_flag=True, default=False, help="Enable plan-first mode for all tasks.")
@click.option("--auto", is_flag=True, default=False, help="Auto-approve all file operations.")
def chat_cmd(priority, plan, auto):
    """[AGENTIC] Start an interactive terminal REPL chat session with workspace tools."""
    from ijachi_router.ui import print_banner
    from ijachi_router.repl import RichREPL

    print_banner()
    repl = RichREPL(priority=priority, plan_mode=plan, auto_approve=auto)
    repl.start()


@main.command(name="status")
def status_cmd():
    """Show active provider health, selected model, and session info."""
    from ijachi_router.health import check_providers_quick, render_provider_card
    from ijachi_router.config import load_config

    cfg = load_config()
    statuses = check_providers_quick(cfg)
    render_provider_card(statuses)


@main.command(name="init")
def init_cmd():
    """Generate an IJACHI.md workspace context file for this project."""
    from ijachi_router.workspace_context import generate_workspace_context
    from pathlib import Path

    generate_workspace_context(Path.cwd(), auto=False)


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


@main.command(name="consensus")
@click.argument("prompt")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default="quality")
def consensus_cmd(prompt, priority):
    """[KILLER FEATURE] Query 2 top models & peer-review solutions for consensus code."""
    from ijachi_router.consensus import consensus_route

    click.echo(click.style("⚖️ Executing Multi-Model Consensus & Peer Review...", fg="cyan"))
    res = consensus_route(prompt=prompt, priority=priority)
    click.echo(res.final_text)
    click.echo()
    click.echo(
        click.style(
            f"[model_a={res.model_a} model_b={res.model_b} consensus_model={res.consensus_model} total_cost=${res.total_cost_usd:.4f}]",
            fg="bright_black",
        )
    )




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
@main.command(name="update")
def update_cmd():
    """[UPDATE] Auto-update ijachi to the latest version."""
    from ijachi_router.updater import update_ijachi

    msg = update_ijachi()
    click.echo(click.style(f"✓ {msg}", fg="green", bold=True))


def code_main():
    """Standalone ijachi / ijachi-code CLI entrypoint tuned specifically for coding tasks."""
    import sys
    known_commands = {
        "route", "stats", "providers", "provider", "update-catalog", "train",
        "serve", "dashboard", "license", "agent", "chat", "fix", "consensus",
        "index", "commit", "update", "banner", "status", "init",
    }
    args = sys.argv[1:]
    if not args:
        sys.argv.insert(1, "chat")
    elif not args[0].startswith("-") and args[0] not in known_commands:
        sys.argv.insert(1, "route")
        if "--priority" not in sys.argv and "-p" not in sys.argv:
            sys.argv.extend(["--priority", "quality"])
    main()


if __name__ == "__main__":
    main()
