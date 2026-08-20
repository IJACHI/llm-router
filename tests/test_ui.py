"""Unit tests for Rich UI Design System & Terminal Styling."""

from __future__ import annotations

import pytest
from ijachi_router.ui import get_neon_banner, get_status_pill, get_badge


def test_neon_banner():
    panel = get_neon_banner()
    assert panel is not None


def test_status_pills():
    pill_active = get_status_pill(active=True, is_free=False)
    assert "ACTIVE" in pill_active

    pill_free = get_status_pill(active=True, is_free=True)
    assert "FREE" in pill_free

    pill_unset = get_status_pill(active=False, is_free=False)
    assert "UNSET" in pill_unset


def test_badges():
    badge_code = get_badge("code")
    assert "CODE" in badge_code

    badge_reasoning = get_badge("reasoning")
    assert "REASONING" in badge_reasoning

    badge_fast = get_badge("fast")
    assert "ULTRA-FAST" in badge_fast
