"""Unit tests for Auto-Updater Engine."""

from __future__ import annotations

import pytest
from ijachi_router.updater import update_ijachi


def test_update_ijachi_execution():
    msg = update_ijachi()
    assert msg is not None
    assert "updated" in msg.lower() or "notice" in msg.lower() or "upgraded" in msg.lower()
