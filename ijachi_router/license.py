"""License verification and feature gating for ijachi-llm-router.

Handles Pro tier feature gating, license key validation, and paywall prompts.
"""

from __future__ import annotations

import base64
import json
import os
import time
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


# Ed25519 public key of the license issuer. Keys are minted with scripts/license_admin.py,
# which holds the matching private key; this package can verify keys but never create them.
_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAOx+Tmtg1PZCSRI2fSJJIoKwVpKXJqWckmpLopxQU12w=
-----END PUBLIC KEY-----
"""

_PREFIX = "IJPRO-"


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encode_license(private_key, sub: str, plan: str = "pro", exp: int | None = None) -> str:
    """Issuer-side: sign a license payload. ``private_key`` is an Ed25519PrivateKey."""
    payload = {"v": 1, "sub": sub, "plan": plan, "iat": int(time.time()), "exp": exp}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(private_key.sign(body.encode("ascii")))
    return f"{_PREFIX}{body}.{sig}"


def decode_license(key: str, public_key_pem: bytes | None = None) -> dict:
    """Verify signature and expiry; return the payload. Raises ValueError when invalid."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise ValueError("the 'cryptography' package is required to verify license keys") from e

    if not key.startswith(_PREFIX) or "." not in key[len(_PREFIX):]:
        raise ValueError("legacy or malformed key")
    body, _, sig = key[len(_PREFIX):].partition(".")
    pub = load_pem_public_key(public_key_pem or _PUBLIC_KEY_PEM)
    try:
        pub.verify(_b64d(sig), body.encode("ascii"))
    except (InvalidSignature, ValueError, TypeError) as e:
        raise ValueError("signature does not verify") from e
    payload = json.loads(_b64d(body))
    exp = payload.get("exp")
    if exp is not None and time.time() > float(exp):
        raise ValueError("license expired")
    return payload


def validate_license_key(key: str | None) -> tuple[bool, str]:
    """Validate a Pro license key string. Returns (is_valid, message)."""
    if not key:
        return False, "No license key provided."

    key = key.strip()
    if not key.startswith(_PREFIX):
        return False, "Invalid key format. Pro license keys must start with 'IJPRO-'."
    if len(key) < 12:
        return False, "License key is too short or malformed."
    try:
        payload = decode_license(key)
    except ValueError as e:
        if "legacy" in str(e):
            return False, "This key uses the old unsigned format. Please request a new signed key."
        if "expired" in str(e):
            return False, "This license key has expired."
        return False, "License key is not valid (signature check failed)."
    return True, f"Valid Pro License ({payload.get('sub', 'unknown')})"


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
