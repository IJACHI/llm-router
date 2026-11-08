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


@main.command(name="update")
def update_cmd():
    """Check and pull latest updates from GitHub."""
    from ijachi_router.updater import update_ijachi
    msg = update_ijachi()
    click.echo(msg)


@main.command(name="train")
def train_cmd():
    """Retrain the prompt classifier (safe JSON weights) and report its accuracy."""
    from ijachi_router.routing.classifier import retrain_safe_model
    click.echo("Training classifier from data/train_data.csv ...")
    try:
        meta = retrain_safe_model()
    except ImportError:
        raise click.ClickException("scikit-learn is required for training: pip install scikit-learn")
    msg = f"✓ Trained on {meta['n_examples']} examples · cross-validated accuracy {meta['cv_accuracy']:.1%}"
    if "eval_accuracy" in meta:
        msg += f" · held-out accuracy {meta['eval_accuracy']:.1%}"
    click.echo(click.style(msg, fg="green"))


@main.command(name="eval")
@click.option("--mode", "modes", default="efficient", help="Comma-separated routing modes to compare (efficient,cheapest,best,best-fit).")
@click.option("--model", default=None, help="Pin one model for every task (e.g. claude-sonnet-5-5).")
@click.option("--local-only", is_flag=True, help="Only use local (Ollama) models — free.")
@click.option("--allow-providers", default=None, help="Comma-separated providers to allow.")
@click.option("--task", "only", multiple=True, help="Only run tasks whose id contains this (repeatable).")
@click.option("--repeat", default=1, type=int, help="Runs per task and mode (models are not deterministic).")
@click.option("--max-turns", default=30, type=int)
@click.option("--no-sandbox", is_flag=True, help="Run commands without the OS sandbox.")
@click.option("--no-record", is_flag=True, help="Do not feed results into learned routing.")
@click.option("--tasks-dir", default=None, type=click.Path(exists=True, file_okay=False))
def eval_cmd(modes, model, local_only, allow_providers, only, repeat, max_turns, no_sandbox, no_record, tasks_dir):
    """Measure the agent: solve rate, cost per solved task and time on the evaluation suite."""
    from pathlib import Path as _P

    from ijachi_router.evals import TASKS_DIR, load_tasks, run_task, save_results, summarize

    tasks = load_tasks(_P(tasks_dir) if tasks_dir else TASKS_DIR, list(only) or None)
    if not tasks:
        raise click.ClickException("No tasks found.")
    allow = {p.strip() for p in allow_providers.split(",")} if allow_providers else None
    mode_list = [m.strip() for m in modes.split(",") if m.strip()]
    if not local_only and not click.confirm(
        f"Run {len(tasks) * len(mode_list) * repeat} agent tasks? This calls your configured providers and can cost money.",
        default=True,
    ):
        return
    results = []
    for mode in mode_list:
        for t in tasks:
            for _ in range(repeat):
                r = run_task(t, mode, local_only=local_only, model=model, allow_providers=allow,
                             max_turns=max_turns, sandbox=not no_sandbox, record=not no_record)
                results.append(r)
                mark = "✓" if r.solved else ("·" if not r.valid else "✗")
                click.echo(f"  {mark} [{mode}] {t.id:<26} {r.seconds:>6.1f}s  ${r.cost_usd:.4f}  {r.model or '-':<32} {'' if r.solved else r.reason[:70]}")
    summary = summarize(results)
    click.echo("")
    for mode, s in summary.items():
        cps = f"${s['cost_per_solved_usd']:.4f}" if s["cost_per_solved_usd"] is not None else "n/a"
        click.echo(click.style(
            f"{mode:<10} solved {s['solved']}/{s['tasks']} ({s['solve_rate']:.0%})  total ${s['total_cost_usd']:.4f}  "
            f"per solved {cps}  avg {s['avg_seconds']}s  models: {', '.join(s['models'])}", fg="green"))
    invalid = [r.task for r in results if not r.valid]
    if invalid:
        click.echo(click.style(f"Invalid tasks (already passing before the agent ran): {sorted(set(invalid))}", fg="yellow"))
    path = save_results(results, {"modes": mode_list, "model": model, "local_only": local_only, "repeat": repeat})
    click.echo(f"Results saved to {path}")


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
@click.option("--token", default=None, help="API access token clients must send (default: $IJACHI_SERVER_TOKEN or a random one).")
def serve_cmd(host, port, license_key, token):
    """[PRO] Launch REST API gateway & dashboard."""
    from ijachi_router.license import set_license_key
    from ijachi_router.server import start_server

    if license_key:
        set_license_key(license_key)

    server = start_server(host=host, port=port, token=token)
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
