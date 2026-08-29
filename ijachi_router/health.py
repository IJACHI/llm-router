"""Provider Health Dashboard for ijachi-code.

Shows a live card of all configured providers: which are active, which
are missing API keys, which are offline, and which model is selected.

This surfaces the "silent failure" problem — where Gemini was being
skipped without the user having any visibility into why.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()


@dataclass
class ProviderStatus:
    provider: str
    model_id: str
    available: bool
    has_key: bool
    selected: bool = False
    error: str = ""
    speed_tier: str = "fast"
    cost_str: str = "~free"


def check_providers_quick(config) -> list[ProviderStatus]:
    """
    Non-blocking provider health check.
    Checks key presence; does NOT make live API calls (to keep startup fast).
    """
    from ijachi_router.config import _PROVIDER_ENV_KEYS
    import os

    statuses: list[ProviderStatus] = []
    seen: set[str] = set()
    selected_provider = None

    # Determine top-ranked available model
    from ijachi_router.core import _rank_models
    from ijachi_router.classifier import predict_category, complexity_score
    try:
        ranked = _rank_models(config, "simple-qa", 0.1)
        if ranked:
            selected_provider = ranked[0].provider + "/" + ranked[0].model_id
    except Exception:
        pass

    for model in config.models:
        key = f"{model.provider}/{model.model_id}"
        if key in seen:
            continue
        seen.add(key)

        env_key = _PROVIDER_ENV_KEYS.get(model.provider)
        has_key = True if env_key is None else bool(os.environ.get(env_key))
        is_available = model.provider in config.available_providers
        is_selected = selected_provider == key

        cost_str = "FREE" if model.input_per_1k == 0 else f"${model.input_per_1k:.4f}/1k"

        statuses.append(ProviderStatus(
            provider=model.provider,
            model_id=model.model_id,
            available=is_available,
            has_key=has_key,
            selected=is_selected,
            speed_tier=model.speed_tier,
            cost_str=cost_str,
        ))

    # Sort: selected first, available next, unavailable last
    statuses.sort(key=lambda s: (0 if s.selected else (1 if s.available else 2), s.provider))
    return statuses


def render_provider_card(statuses: list[ProviderStatus]) -> None:
    """Print a compact provider health panel."""
    table = Table(
        border_style="bright_blue",
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
        min_width=62,
    )
    table.add_column("", width=3, justify="center")
    table.add_column("Provider / Model", style="white")
    table.add_column("Speed", style="dim", width=8)
    table.add_column("Cost", style="dim green", width=12)
    table.add_column("", width=10)

    shown = 0
    for s in statuses:
        if shown >= 8:
            break  # Limit display to keep startup concise
        shown += 1

        # Status icon
        if s.selected:
            icon = Text("✦", style="bold cyan")
            suffix = Text(" ACTIVE", style="bold cyan")
        elif s.available:
            icon = Text("✅", style="green")
            suffix = Text("", style="")
        elif not s.has_key:
            icon = Text("⚪", style="dim")
            suffix = Text(" no key", style="dim")
        else:
            icon = Text("🔴", style="red")
            suffix = Text(" offline", style="dim red")

        speed_style = {"fast": "green", "medium": "yellow", "slow": "red"}.get(s.speed_tier, "white")
        speed_text = Text(s.speed_tier, style=speed_style)

        table.add_row(
            icon,
            f"{s.provider}/{s.model_id}",
            speed_text,
            s.cost_str,
            suffix,
        )

    remaining = len(statuses) - shown
    if remaining > 0:
        table.add_row("", f"[dim]... and {remaining} more providers[/dim]", "", "", "")

    from rich.panel import Panel
    console.print(Panel(
        table,
        title="[bold cyan]⚡ IJACHI Provider Status[/bold cyan]",
        border_style="bright_blue",
        padding=(0, 0),
    ))
