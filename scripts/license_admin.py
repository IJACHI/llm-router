#!/usr/bin/env python3
"""Issuer-side license tooling (NOT shipped in the package).

    python scripts/license_admin.py keygen                 # once: create the signing keypair
    python scripts/license_admin.py issue --sub buyer@example.com --days 365
    python scripts/license_admin.py verify IJPRO-...

The private key never leaves the issuer's machine. Only the public key is embedded in
ijachi_router/license.py (_PUBLIC_KEY_PEM). Back the private key up somewhere safe: if it is
lost no new keys can be issued; if it leaks anyone can mint keys (rotate by generating a new
pair and shipping the new public key).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from ijachi_router.license import encode_license, validate_license_key  # noqa: E402

DEFAULT_KEY = Path(os.environ.get("IJACHI_LICENSE_SIGNING_KEY", Path.home() / ".ijachi-llmr" / "license-signing" / "ed25519_private.pem"))


def cmd_keygen(args: argparse.Namespace) -> int:
    path = Path(args.key)
    if path.exists():
        print(f"Refusing to overwrite existing signing key at {path}", file=sys.stderr)
        return 1
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    print(f"Private signing key written to {path} (mode 600). Back it up; never commit it.")
    print("Embed this public key as _PUBLIC_KEY_PEM in ijachi_router/license.py:\n")
    print(pub.decode())
    return 0


def _load_private(path: str) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("signing key is not Ed25519")
    return key


def cmd_issue(args: argparse.Namespace) -> int:
    key = _load_private(args.key)
    exp = int(time.time() + args.days * 86400) if args.days else None
    token = encode_license(key, sub=args.sub, plan=args.plan, exp=exp)
    print(token)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ok, msg = validate_license_key(args.license)
    print(msg)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=str(DEFAULT_KEY), help="Path to the Ed25519 private signing key")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="Create a new signing keypair")
    p_issue = sub.add_parser("issue", help="Issue a signed license key")
    p_issue.add_argument("--sub", required=True, help="Customer identifier (e.g. email or order id)")
    p_issue.add_argument("--plan", default="pro")
    p_issue.add_argument("--days", type=int, default=365, help="Validity in days (0 = never expires)")
    p_verify = sub.add_parser("verify", help="Verify a license key against the embedded public key")
    p_verify.add_argument("license")
    args = ap.parse_args()
    return {"keygen": cmd_keygen, "issue": cmd_issue, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
