"""Usage metrics: append-only JSONL log + rich stats table.

Every routed call appends one JSON line to ~/.ijachi-llmr/history.jsonl.
``print_stats()`` reads that file and renders a summary table with rich.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ijachi_router.providers.base import GenerationResult

_HISTORY_PATH = Path.home() / ".ijachi-llmr" / "history.jsonl"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_result(result: "GenerationResult") -> None:
    """Append *result* as a JSON line to ~/.ijachi-llmr/history.jsonl."""
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": result.provider,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "latency_s": result.latency_s,
    }
    with _HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _load_history() -> list[dict]:
    if not _HISTORY_PATH.exists():
        return []
    records = []
    with _HISTORY_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


load_history = _load_history



def print_stats() -> None:
    """Print a rich table summarising all recorded calls."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
    except ImportError:
        _print_stats_plain()
        return

    records = _load_history()
    if not records:
        print("No history found. Run llmr to start tracking usage.")
        return

    console = Console()

    # ── Overall summary ─────────────────────────────────────────────────────
    total_cost = sum(r.get("cost_usd", 0) for r in records)
    total_calls = len(records)
    avg_latency = sum(r.get("latency_s", 0) for r in records) / total_calls

    console.print()
    console.print(
        f"[bold cyan]ijachi-llm-router usage[/bold cyan]  "
        f"[dim]{total_calls} calls · "
        f"[green]${total_cost:.4f}[/green] total · "
        f"{avg_latency:.2f}s avg latency[/dim]"
    )
    console.print()

    # ── Per-model breakdown ──────────────────────────────────────────────────
    model_stats: dict[str, dict] = {}
    for r in records:
        key = r.get("model", "unknown")
        if key not in model_stats:
            model_stats[key] = {
                "provider": r.get("provider", "?"),
                "calls": 0,
                "cost": 0.0,
                "latency_sum": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
            }
        s = model_stats[key]
        s["calls"] += 1
        s["cost"] += r.get("cost_usd", 0)
        s["latency_sum"] += r.get("latency_s", 0)
        s["tokens_in"] += r.get("input_tokens", 0)
        s["tokens_out"] += r.get("output_tokens", 0)

    table = Table(
        title="Spend by Model",
        box=box.ROUNDED,
        show_footer=True,
        highlight=True,
    )
    table.add_column("Model", style="bold", footer="TOTAL")
    table.add_column("Provider", style="dim")
    table.add_column("Calls", justify="right", footer=str(total_calls))
    table.add_column("Cost (USD)", justify="right", style="green",
                     footer=f"${total_cost:.4f}")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Tokens In", justify="right", style="dim")
    table.add_column("Tokens Out", justify="right", style="dim")

    for model, s in sorted(model_stats.items(), key=lambda x: -x[1]["cost"]):
        avg_lat = s["latency_sum"] / s["calls"]
        table.add_row(
            model,
            s["provider"],
            str(s["calls"]),
            f"${s['cost']:.4f}",
            f"{avg_lat:.2f}s",
            str(s["tokens_in"]),
            str(s["tokens_out"]),
        )

    console.print(table)
    console.print()


def _print_stats_plain() -> None:
    """Fallback stats printer when rich is not installed."""
    records = _load_history()
    if not records:
        print("No history found.")
        return

    total_cost = sum(r.get("cost_usd", 0) for r in records)
    print(f"\nTotal calls: {len(records)}  Total cost: ${total_cost:.4f}\n")
    print(f"{'Model':<30} {'Calls':>6} {'Cost':>10} {'Avg Lat':>10}")
    print("-" * 60)

    model_stats: dict[str, dict] = {}
    for r in records:
        key = r.get("model", "unknown")
        if key not in model_stats:
            model_stats[key] = {"calls": 0, "cost": 0.0, "latency_sum": 0.0}
        model_stats[key]["calls"] += 1
        model_stats[key]["cost"] += r.get("cost_usd", 0)
        model_stats[key]["latency_sum"] += r.get("latency_s", 0)

    for model, s in sorted(model_stats.items(), key=lambda x: -x[1]["cost"]):
        avg = s["latency_sum"] / s["calls"]
        print(f"{model:<30} {s['calls']:>6} ${s['cost']:>9.4f} {avg:>9.2f}s")
    print()
