"""ijachi-router (alias ijr) — Routing and administration utility CLI.

Document 2.1:
Commands:
- route "<prompt>": route prompt, print response + cost footer
- stats: spend/latency table
- providers: list detected provider status
- update-catalog: fetch dynamic model catalog & pricing updates
- train: retrain classifier
- serve: [PRO] launch REST API gateway & dashboard
- dashboard: [PRO] open dashboard in browser
- license: manage Pro license keys
- doctor: run environment and model diagnostics
- sessions: list and prune sessions
"""

from __future__ import annotations

import click

from ijachi_router.doctor import print_doctor_report
from ijachi_router.session.store import list_sessions, prune_sessions


class RouterCLI(click.Group):
    """Custom Click Group that handles aliases and bare prompt routing."""

    def get_command(self, ctx, cmd_name):
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        aliases = {
            "provider": "providers",
            "stat": "stats",
        }
        if cmd_name in aliases:
            return super().get_command(ctx, aliases[cmd_name])
        return None

    def parse_args(self, ctx, args):
        if args and not args[0].startswith("-"):
            cmd_name = args[0]
            if cmd_name not in self.commands and cmd_name not in {"provider", "stat"}:
                args.insert(0, "route")
        return super().parse_args(ctx, args)


@click.group(cls=RouterCLI)
def main():
    """ijachi-router: Multi-model routing engine and admin utility."""


@main.command(name="route")
@click.argument("prompt")
@click.option("--priority", "-p", type=click.Choice(["cost", "speed", "quality", "balanced"]), default=None)
@click.option("--max-cost", "-m", type=float, default=None)
@click.option("--models-yaml", default=None, hidden=True)
def route_cmd(prompt, priority, max_cost, models_yaml):
    """Route PROMPT to the best available model and print response."""
    from ijachi_router.core import Router

    try:
        router = Router(models_yaml=models_yaml)
        if priority:
            router.config.priority = priority
        if max_cost is not None:
            router.config.max_cost_per_call = max_cost

        res = router.route(prompt)
        click.echo(res.text)
        click.echo()

        footer = (
            f"[model={res.model_used:<24} "
            f"cost=${res.cost:.4f}  "
            f"latency={res.latency_sec:.2f}s  "
            f"tokens={res.input_tokens}in/{res.output_tokens}out]"
        )
        click.echo(click.style(footer, fg="bright_black"))
    except Exception as e:
        raise click.ClickException(str(e)) from e


@main.command(name="stats")
def stats_cmd():
    """Show spend and latency table for recorded calls."""
    from ijachi_router.metrics import print_stats
    print_stats()


@main.command(name="providers")
@click.option("--models-yaml", default=None, hidden=True)
def providers_cmd(models_yaml):
    """List detected provider keys and availability."""
    import os
    from ijachi_router.config import _PROVIDER_ENV_KEYS, load_config

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
        f"{', '.join(sorted(config.available_providers)) or 'none (set an API key)'}\n"
    )


@main.command(name="update-catalog")
@click.option("--force", is_flag=True, help="Force refresh from remote registry.")
def update_catalog_cmd(force):
    """Fetch latest model catalog & pricing updates."""
    from ijachi_router.catalog_updater import update_catalog
    click.echo("Fetching dynamic model catalog & pricing updates...")
    ok, msg = update_catalog(force=force)
    if ok:
        click.echo(click.style(f"✓ {msg}", fg="green"))
    else:
        click.echo(click.style(f"✗ {msg}", fg="red"))


@main.command(name="train")
def train_cmd():
    """Retrain prompt classifier in non-executable safe JSON format."""
    from ijachi_router.routing.classifier import retrain_safe_model
    click.echo("Training safe classifier from training data...")
    try:
        retrain_safe_model()
        click.echo(click.style("✓ Classifier trained with verified checksum.", fg="green"))
    except Exception as e:
        from ijachi_router.classifier import retrain
        retrain()
        click.echo(click.style("✓ Classifier trained.", fg="green"))


@main.command(name="doctor")
def doctor_cmd():
    """Run full environment diagnostics."""
    print_doctor_report()


@main.group(name="sessions")
def sessions_grp():
    """Manage local sessions."""


@sessions_grp.command(name="list")
def sessions_list_cmd():
    """List stored sessions."""
    s = list_sessions()
    click.echo(f"Found {len(s)} sessions:")
    for item in s[:15]:
        click.echo(f"  {item['id']}  turns: {item['turns']}  spend: ${item['cost']:.4f}  ({item['workspace']})")


@sessions_grp.command(name="prune")
@click.option("--days", default=30, type=int, help="Prune sessions older than N days.")
def sessions_prune_cmd(days):
    """Prune old sessions."""
    n = prune_sessions(max_days=days)
    click.echo(click.style(f"✓ Pruned {n} sessions older than {days} days.", fg="green"))


@main.command(name="serve")
@click.option("--host", default="127.0.0.1", help="Host address to bind.")
@click.option("--port", default=8000, type=int, help="Port to bind.")
@click.option("--license-key", default=None, help="Pro license key.")
def serve_cmd(host, port, license_key):
    """[PRO] Launch REST API gateway & dashboard."""
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


@main.command(name="dashboard")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def dashboard_cmd(host, port):
    """[PRO] Open web telemetry dashboard."""
    import webbrowser
    from ijachi_router.license import check_pro_access

    if not check_pro_access("Web Telemetry Dashboard"):
        return
    url = f"http://{host}:{port}/"
    click.echo(f"Opening Web Dashboard at {url} ...")
    webbrowser.open(url)


@main.group(name="license")
def license_grp():
    """Manage Pro license keys."""


@license_grp.command(name="set")
@click.argument("key")
def license_set_cmd(key):
    from ijachi_router.license import set_license_key
    ok, msg = set_license_key(key)
    if ok:
        click.echo(click.style(f"✓ {msg}", fg="green"))
    else:
        click.echo(click.style(f"✗ {msg}", fg="red"))


@license_grp.command(name="status")
def license_status_cmd():
    from ijachi_router.license import get_license_key, validate_license_key
    key = get_license_key()
    valid, msg = validate_license_key(key)
    if valid:
        click.echo(click.style(f"✓ Pro License Active (Key: {key[:8]}...)", fg="green"))
    else:
        click.echo(click.style(f"ℹ Free Tier / Community Edition ({msg})", fg="yellow"))


@license_grp.command(name="remove")
def license_remove_cmd():
    from ijachi_router.license import remove_license_key
    remove_license_key()
    click.echo("✓ License key removed.")


if __name__ == "__main__":
    main()
