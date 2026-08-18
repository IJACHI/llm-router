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


def test_validate_valid_key():
    valid, msg = validate_license_key("IJPRO-DEMO-TEST-KEY-2026")
    assert valid
    assert "Valid Pro License" in msg


def test_license_set_and_remove(tmp_path, monkeypatch):
    test_key_file = tmp_path / "license.key"
    monkeypatch.setattr("ijachi_router.license._LICENSE_FILE", test_key_file)
    monkeypatch.setattr("ijachi_router.license._CACHE_DIR", tmp_path)
    monkeypatch.delenv("IJACHI_ROUTER_LICENSE_KEY", raising=False)

    assert not is_pro_active()

    ok, msg = set_license_key("IJPRO-TEST-123456789")
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
