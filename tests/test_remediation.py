"""Integration/regression tests for the remediated gaps in ijachi-llm-router."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from ijachi_router.providers.base import GenerationResult


# ---------------------------------------------------------------------------
# Welcome card
# ---------------------------------------------------------------------------

def test_welcome_card_renders_without_table_in_text():
    """Regression: the welcome card must be a Rich container, not Text.assemble around a Table."""
    from ijachi_router.ui import get_welcome_card
    from rich.console import Group
    from rich.columns import Columns
    from rich.text import Text

    card = get_welcome_card(model="auto (balanced)", workspace=str(Path.cwd()))
    assert card is not None
    # The body should be a multi-column layout (Columns) or a Group — never raw Text.
    assert isinstance(card.renderable, (Group, Columns))
    assert not isinstance(card.renderable, Text)


# ---------------------------------------------------------------------------
# code_main routing
# ---------------------------------------------------------------------------

def test_code_main_routes_bare_prompt_with_quality_priority():
    """Bare prompts should be prepended with 'route' and default to quality priority."""
    from cli import code_main

    captured = {}

    def _fake_main():
        captured["argv"] = sys.argv.copy()

    with patch.object(sys, "argv", ["ijachi", "hello world"]):
        with patch("cli.main", side_effect=_fake_main):
            code_main()

    assert captured["argv"][1] == "route"
    assert captured["argv"][-2:] == ["--priority", "quality"]


def test_code_main_leaves_known_commands_untouched():
    """Known ecosystem commands must not be mis-routed to 'route'."""
    from cli import code_main

    captured = {}

    def _fake_main():
        captured["argv"] = sys.argv.copy()

    for cmd in ("memory", "pr-review", "release", "skills", "theme"):
        with patch.object(sys, "argv", ["ijachi", cmd]):
            with patch("cli.main", side_effect=_fake_main):
                code_main()
        assert captured["argv"][1] == cmd
        assert "route" not in captured["argv"]


# ---------------------------------------------------------------------------
# SDK endpoint URLs
# ---------------------------------------------------------------------------

def test_sdk_endpoints_target_v1_route():
    """Generated SDKs must POST to /v1/route, not the legacy /v1/chat/completions."""
    from ijachi_router.sdk_generator import SDKGenerator

    gen = SDKGenerator()
    assert "/v1/route" in gen.TYPESCRIPT_SDK
    assert "/v1/route" in gen.GO_SDK
    assert "/v1/chat/completions" not in gen.TYPESCRIPT_SDK
    assert "/v1/chat/completions" not in gen.GO_SDK


# ---------------------------------------------------------------------------
# Prompt engine stash
# ---------------------------------------------------------------------------

def test_prompt_engine_stash_handler_does_not_shadow_stash_list():
    """Regression: the Ctrl+S handler was named _stash and shadowed the module-level list."""
    from ijachi_router import prompt_engine as pe_mod

    assert isinstance(pe_mod._stash, list)
    assert callable(pe_mod._stash_handler)


def test_prompt_engine_stash_saves_and_restores_draft():
    """Ctrl+S should stash non-empty text and restore it on a second press."""
    from ijachi_router.prompt_engine import _stash_handler, _stash

    _stash.clear()

    class _FakeBuffer:
        def __init__(self, text):
            self.text = text
            self.document = MagicMock()
        def insert_text(self, txt):
            self.text += txt
        def set_document(self, doc):
            self.text = ""
            self.document = doc

    class _FakeEvent:
        def __init__(self, text):
            self.current_buffer = _FakeBuffer(text)
            self.app = MagicMock()
            self.app.output = MagicMock()

    # Stash
    ev1 = _FakeEvent("draft line")
    _stash_handler(ev1)
    assert _stash
    assert ev1.current_buffer.text == ""

    # Restore
    ev2 = _FakeEvent("")
    _stash_handler(ev2)
    assert ev2.current_buffer.text == "draft line"
    assert not _stash


# ---------------------------------------------------------------------------
# Model manager provider validation
# ---------------------------------------------------------------------------

def test_model_manager_rejects_unknown_provider(tmp_path) -> None:
    """Only providers in REGISTRY should be accepted by 'models add'."""
    from ijachi_router.model_manager import ModelManager

    fake_yaml = tmp_path / "models.yaml"
    fake_yaml.write_text(
        yaml.safe_dump({"version": "1.0", "models": []}), encoding="utf-8"
    )
    mm = ModelManager(models_yaml=fake_yaml)
    msg = mm.add_model(model_id="fake-model", provider="bogus-provider")
    assert "Unknown provider" in msg
    assert "bogus-provider" in msg


def test_model_manager_accepts_known_provider(tmp_path) -> None:
    """A registered provider should be added successfully."""
    from ijachi_router.model_manager import ModelManager
    from ijachi_router.providers import REGISTRY

    known = next(iter(REGISTRY.keys()))
    fake_yaml = tmp_path / "models.yaml"
    fake_yaml.write_text(
        yaml.safe_dump({"version": "1.0", "models": []}), encoding="utf-8"
    )
    mm = ModelManager(models_yaml=fake_yaml)
    msg = mm.add_model(model_id="my-known-model", provider=known)
    assert "Successfully added" in msg


# ---------------------------------------------------------------------------
# Catalog updater filtering
# ---------------------------------------------------------------------------

def test_update_catalog_filters_unknown_providers(monkeypatch, tmp_path):
    """Remote catalog updates must not poison the matrix with unknown providers."""
    from ijachi_router import catalog_updater as cu
    from ijachi_router.providers import REGISTRY

    # Redirect cache to a temp file so we do not pollute the user's home dir.
    cache_file = tmp_path / "models_cache.yaml"
    monkeypatch.setattr(cu, "_MODELS_CACHE_FILE", cache_file)

    remote_sample = [
        {
            "provider": "unknown-remote-dump",
            "model_id": "unknown/thing",
            "tags": ["simple-qa"],
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "max_context": 4096,
            "speed_tier": "fast",
        },
        {
            "provider": next(iter(REGISTRY.keys())),
            "model_id": "registered/new-model",
            "tags": ["simple-qa"],
            "input_per_1k": 0.001,
            "output_per_1k": 0.002,
            "max_context": 4096,
            "speed_tier": "fast",
        },
    ]
    monkeypatch.setattr(cu, "fetch_remote_catalog", lambda: remote_sample)

    ok, msg = cu.update_catalog(force=True)
    assert ok, msg

    assert cache_file.exists()
    cached = yaml.safe_load(cache_file.read_text(encoding="utf-8"))
    providers = {m["provider"] for m in cached.get("models", [])}
    assert "unknown-remote-dump" not in providers
    assert next(iter(REGISTRY.keys())) in providers


def test_restore_default_catalog_removes_cache(monkeypatch, tmp_path):
    """--restore-defaults should delete the dynamic cache."""
    from ijachi_router import catalog_updater as cu

    cache_file = tmp_path / "models_cache.yaml"
    cache_file.write_text("models: []", encoding="utf-8")
    monkeypatch.setattr(cu, "_MODELS_CACHE_FILE", cache_file)

    ok, msg = cu.restore_default_catalog()
    assert ok, msg
    assert not cache_file.exists()


# ---------------------------------------------------------------------------
# Humanizer patterns
# ---------------------------------------------------------------------------

def test_humanizer_strips_new_opener_patterns():
    """Newly added AI opener patterns should be removed in full humanization mode."""
    from ijachi_router.humanizer import humanize

    samples = [
        ("How can I help you today?\nThe answer is 42.", "How can I help you today"),
        ("Hello! It's great to meet you.\nHere is the answer.", "great to meet you"),
        ("What would you like to explore today?\nThe answer is 42.", "explore today"),
    ]
    for sample, opener in samples:
        out = humanize(sample, mode="full")
        assert opener not in out
        assert "answer" in out.lower()


def test_humanizer_strips_closer_patterns():
    """Common closer patterns should be removed."""
    from ijachi_router.humanizer import humanize

    text = "The answer is 42.\n\nIf you need anything else, just let me know."
    out = humanize(text, mode="full")
    assert "If you need anything else" not in out
    assert "42" in out


# ---------------------------------------------------------------------------
# Core force_model matching
# ---------------------------------------------------------------------------

def test_force_model_exact_match_preferred_over_mini():
    """Regression: 'gpt-4o' must not accidentally select 'gpt-4o-mini'."""
    from ijachi_router.core import Router
    from pathlib import Path

    models_yaml = Path(__file__).parent.parent / "models.yaml"
    router = Router(models_yaml=models_yaml)

    mock_gpt4o = MagicMock()
    mock_gpt4o.name = "openai"
    mock_gpt4o.generate.return_value = GenerationResult(
        text="ok", provider="openai", model="gpt-4o",
        input_tokens=1, output_tokens=1, cost_usd=0.0, latency_s=0.0,
    )

    with patch("ijachi_router.core._build_provider", return_value=mock_gpt4o):
        with patch("ijachi_router.core.log_result"):
            router.config.available_providers = {"openai"}
            res = router.route("hi", force_model="gpt-4o")

    assert res.model == "gpt-4o"


# ---------------------------------------------------------------------------
# Server endpoints are ungated
# ---------------------------------------------------------------------------

def test_server_route_and_stats_unauthenticated(tmp_path, monkeypatch):
    """Local REST endpoints must be usable without a Pro license."""
    from ijachi_router.server import start_server, RouterRequestHandler
    from ijachi_router import metrics

    # Use an empty metrics history so /v1/stats returns zeros.
    hist_file = tmp_path / "metrics_history.jsonl"
    monkeypatch.setattr(metrics, "_HISTORY_PATH", hist_file)

    server = start_server(host="127.0.0.1", port=0)
    port = server.server_address[1]

    def _run():
        server.serve_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    try:
        stats_resp = requests.get(f"{base}/v1/stats", timeout=2)
        assert stats_resp.status_code == 200
        assert stats_resp.json()["status"] == "success"

        fake_result = GenerationResult(
            text="hello", provider="openai", model="gpt-4o-mini",
            input_tokens=1, output_tokens=1, cost_usd=0.0001, latency_s=0.1,
        )
        with patch("ijachi_router.server.route", return_value=fake_result):
            route_resp = requests.post(
                f"{base}/v1/route",
                json={"prompt": "hi", "priority": "balanced"},
                timeout=2,
            )
            assert route_resp.status_code == 200
            body = route_resp.json()
            assert body["text"] == "hello"
            assert body["provider"] == "openai"
            assert body["model"] == "gpt-4o-mini"

        mock_agent_result = MagicMock()
        mock_agent_result.final_text = "done"
        mock_agent_result.steps = []
        mock_agent_result.total_cost_usd = 0.0
        mock_agent_result.completed = True

        with patch("ijachi_router.agent.AgenticRouter") as mock_agent_cls:
            instance = MagicMock()
            instance.run.return_value = mock_agent_result
            mock_agent_cls.return_value = instance
            agent_resp = requests.post(
                f"{base}/v1/agent/run",
                json={"task": "say hi", "max_steps": 1},
                timeout=2,
            )
            assert agent_resp.status_code == 200
            assert agent_resp.json()["status"] == "success"
    finally:
        server.shutdown()
        server.server_close()
