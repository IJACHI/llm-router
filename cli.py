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
    args = sys.argv[1:]
    if args and not args[0].startswith("-") and args[0] not in {"route", "stats", "providers", "provider", "update-catalog", "train", "serve", "dashboard", "license"}:
        sys.argv.insert(1, "route")
        if "--priority" not in sys.argv and "-p" not in sys.argv:
            sys.argv.extend(["--priority", "quality"])
    main()


if __name__ == "__main__":
    main()
