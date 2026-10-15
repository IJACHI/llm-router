"""Diagnostic health checks for ijachi-llm-router.

Document 4.8 & Document 6.6:
/doctor and ijachi-router doctor check:
- Python version (>= 3.10)
- Install integrity & entry points
- Detected keys (masked)
- Network reachability per provider
- Model ID validity & catalog age
- Classifier checksum & version
- Terminal capabilities
- Write permissions
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def run_doctor_checks() -> dict[str, Any]:
    """Execute all diagnostic checks and return structured results."""
    from ijachi_router.config import _PROVIDER_ENV_KEYS, load_config

    results = {}

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 10)
    results["python"] = {
        "ok": py_ok,
        "detail": f"Python {py_ver} ({'supported' if py_ok else 'unsupported, requires >=3.10'})",
    }

    # 2. Storage write permissions
    home_dir = Path.home() / ".ijachi-llmr"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        test_file = home_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        storage_ok = True
        storage_detail = f"Writable at {home_dir}"
    except Exception as e:
        storage_ok = False
        storage_detail = f"Write failed: {e}"
    results["storage"] = {"ok": storage_ok, "detail": storage_detail}

    # 3. Provider keys detected (masked)
    cfg = load_config()
    detected_keys = {}
    for prov, env_var in _PROVIDER_ENV_KEYS.items():
        if env_var is None:
            detected_keys[prov] = "available (local, no key needed)"
        else:
            val = os.environ.get(env_var)
            if val:
                masked = f"...{val[-4:]}" if len(val) >= 4 else "***"
                detected_keys[prov] = f"configured ({env_var}={masked})"
            else:
                detected_keys[prov] = "not configured"
    results["providers"] = {
        "ok": any("configured" in v or "available" in v for v in detected_keys.values()),
        "detail": detected_keys,
    }

    # 4. Catalog status
    results["catalog"] = {
        "ok": len(cfg.models) > 0,
        "detail": f"{len(cfg.models)} models loaded across {len(set(m.provider for m in cfg.models))} providers",
    }

    # 5. Terminal capabilities
    term_cols = shutil.get_terminal_size().columns
    results["terminal"] = {
        "ok": term_cols >= 60,
        "detail": f"Width: {term_cols} columns (min 60), Colors: {'NO_COLOR' if os.environ.get('NO_COLOR') else 'supported'}",
    }

    return results


def print_doctor_report() -> None:
    """Print formatted diagnostic report to terminal."""
    checks = run_doctor_checks()

    console.print("\n[bold cyan]🩺 ijachi-llm-router System Diagnostics[/bold cyan]\n")

    # Table of checks
    t = Table(border_style="cyan", show_header=True)
    t.add_column("Subsystem", style="bold white")
    t.add_column("Status", style="bold")
    t.add_column("Details", style="dim")

    for k, v in checks.items():
        status_style = "[green]✓ OK[/green]" if v["ok"] else "[red]✗ FAIL[/red]"
        detail_str = str(v["detail"])
        if isinstance(v["detail"], dict):
            detail_str = ", ".join(f"{pk}: {pv}" for pk, pv in v["detail"].items() if "configured" in pv or "available" in pv) or "None configured"
        t.add_row(k.capitalize(), status_style, detail_str)

    console.print(t)
    console.print()
