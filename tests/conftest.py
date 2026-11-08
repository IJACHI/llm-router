"""Shared test isolation: tests must never write sessions or learned-routing data into the real home dir."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_data(tmp_path, monkeypatch):
    from ijachi_router.routing import outcomes
    from ijachi_router.session import store

    monkeypatch.setattr(outcomes, "OUTCOMES_PATH", tmp_path / "outcomes.json")
    monkeypatch.setattr(store, "_DEFAULT_SESSIONS_ROOT", tmp_path / "home-sessions")
    outcomes.reset_cache()
    yield
    outcomes.reset_cache()
