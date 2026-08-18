"""License verification and feature gating for ijachi-llm-router.

Handles Pro tier feature gating, license key validation, and paywall prompts.
"""

from __future__ import annotations

import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

_CACHE_DIR = Path.home() / ".ijachi-llmr"
_LICENSE_FILE = _CACHE_DIR / "license.key"
PAYSTACK_URL = "https://paystack.shop/pay/enlqpvzflw"

console = Console()


def get_license_key() -> str | None:
    """Retrieve license key from environment variable or local config file."""
    env_key = os.getenv("IJACHI_ROUTER_LICENSE_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    if _LICENSE_FILE.exists():
        try:
            key = _LICENSE_FILE.read_text().strip()
            if key:
                return key
        except Exception:
            pass

    return None


def validate_license_key(key: str | None) -> tuple[bool, str]:
    """Validate a Pro license key string.

    Returns (is_valid, message).
    """
    if not key:
        return False, "No license key provided."

    key = key.strip()
    if not key.startswith("IJPRO-"):
        return False, "Invalid key format. Pro license keys must start with 'IJPRO-'."

    if len(key) < 12:
        return False, "License key is too short or malformed."

    return True, "Valid Pro License"


def is_pro_active() -> bool:
    """Check if a valid Pro license is currently active."""
    key = get_license_key()
    valid, _ = validate_license_key(key)
    return valid


def set_license_key(key: str) -> tuple[bool, str]:
    """Save a license key to the local config file (~/.ijachi-llmr/license.key)."""
    valid, msg = validate_license_key(key)
    if not valid:
        return False, msg

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _LICENSE_FILE.write_text(key.strip())
        return True, "License key successfully activated and saved."
    except Exception as e:
        return False, f"Failed to save license key: {e}"


def remove_license_key() -> bool:
    """Remove stored license key."""
    if _LICENSE_FILE.exists():
        try:
            _LICENSE_FILE.unlink()
            return True
        except Exception:
            return False
    return True


def check_pro_access(feature_name: str = "Pro Feature") -> bool:
    """Verify Pro access for a feature.

    If not active, displays a rich Paystack upgrade prompt and returns False.
    """
    if is_pro_active():
        return True

    console.print()
    console.print(
        Panel(
            f"[bold red]🔒 {feature_name} is locked![/bold red]\n\n"
            f"[yellow]{feature_name}[/yellow] is exclusive to [bold cyan]ijachi-llm-router Pro[/bold cyan].\n"
            f"Free tier includes full core CLI routing, local prompt classifier, and statistics.\n\n"
            f"[bold white]👉 Upgrade to Pro on Paystack:[/bold white] [bold underline green]{PAYSTACK_URL}[/bold underline green]\n\n"
            f"[dim]After purchasing, activate your key with:[/dim]\n"
            f"[bold code]  ijachi-router license set IJPRO-YOUR-KEY-HERE[/bold code]\n"
            f"[dim]Or set environment variable:[/dim]\n"
            f"[bold code]  export IJACHI_ROUTER_LICENSE_KEY=IJPRO-YOUR-KEY-HERE[/bold code]",
            title="[bold red]Pro License Required[/bold red]",
            border_style="red",
        )
    )
    console.print()
    return False
