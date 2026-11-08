"""Provider health card tests (live code; legacy REPL/planner tests removed with that code)."""

from __future__ import annotations


def test_provider_status_dataclass():
    from ijachi_router.health import ProviderStatus
    s = ProviderStatus(
        provider="gemini",
        model_id="gemini-3.6-flash",
        available=True,
        has_key=True,
        selected=True,
    )
    assert s.selected is True


def test_check_providers_quick_returns_list():
    from ijachi_router.health import check_providers_quick
    from ijachi_router.config import load_config
    cfg = load_config()
    statuses = check_providers_quick(cfg)
    assert isinstance(statuses, list)
    assert len(statuses) > 0


def test_render_provider_card_no_error():
    from ijachi_router.health import render_provider_card, ProviderStatus
    statuses = [
        ProviderStatus("gemini", "gemini-3.6-flash", True, True, True, speed_tier="fast", cost_str="~free"),
        ProviderStatus("local", "deepseek-r1:7b", False, True, False, speed_tier="slow", cost_str="FREE"),
    ]
    render_provider_card(statuses)  # Should not raise
