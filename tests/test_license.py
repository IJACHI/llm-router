"""Unit tests for license verification and Pro gating."""

from __future__ import annotations

import os
import pytest

from ijachi_router.license import (
    check_pro_access,
    get_license_key,
    is_pro_active,
    remove_license_key,
    set_license_key,
    validate_license_key,
)


def test_validate_invalid_keys():
    valid, msg = validate_license_key(None)
    assert not valid
    assert "No license key" in msg

    valid, msg = validate_license_key("INVALID-KEY")
    assert not valid
    assert "IJPRO-" in msg

    valid, msg = validate_license_key("IJPRO-SHORT")
    assert not valid
    assert "too short" in msg


@pytest.fixture
def issuer(monkeypatch):
    """A throwaway signing keypair whose public half the package trusts during the test."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr("ijachi_router.license._PUBLIC_KEY_PEM", pem)
    return key


def test_validate_valid_key(issuer):
    from ijachi_router.license import encode_license
    valid, msg = validate_license_key(encode_license(issuer, sub="buyer@example.com"))
    assert valid
    assert "Valid Pro License" in msg and "buyer@example.com" in msg


def test_forged_tampered_expired_and_legacy_keys_are_rejected(issuer):
    import time
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ijachi_router.license import encode_license

    assert not validate_license_key("IJPRO-DEMO-TEST-KEY-2026")[0]  # old unsigned format
    forged = encode_license(Ed25519PrivateKey.generate(), sub="attacker")
    assert not validate_license_key(forged)[0]
    good = encode_license(issuer, sub="buyer")
    body, sig = good[len("IJPRO-"):].split(".")
    assert not validate_license_key("IJPRO-" + body[:-2] + "AA." + sig)[0]
    ok, msg = validate_license_key(encode_license(issuer, sub="buyer", exp=int(time.time()) - 10))
    assert not ok and "expired" in msg


def test_license_set_and_remove(tmp_path, monkeypatch, issuer):
    from ijachi_router.license import encode_license
    test_key_file = tmp_path / "license.key"
    monkeypatch.setattr("ijachi_router.license._LICENSE_FILE", test_key_file)
    monkeypatch.setattr("ijachi_router.license._CACHE_DIR", tmp_path)
    monkeypatch.delenv("IJACHI_ROUTER_LICENSE_KEY", raising=False)

    assert not is_pro_active()

    assert not set_license_key("IJPRO-TEST-123456789")[0]
    ok, msg = set_license_key(encode_license(issuer, sub="buyer"))
    assert ok
    assert test_key_file.exists()
    assert is_pro_active()

    ok_rem = remove_license_key()
    assert ok_rem
    assert not is_pro_active()


def test_check_pro_access_gating(monkeypatch, capsys):
    monkeypatch.delenv("IJACHI_ROUTER_LICENSE_KEY", raising=False)
    monkeypatch.setattr("ijachi_router.license.is_pro_active", lambda: False)

    allowed = check_pro_access("Web Dashboard")
    assert not allowed

    monkeypatch.setattr("ijachi_router.license.is_pro_active", lambda: True)
    allowed = check_pro_access("Web Dashboard")
    assert allowed
