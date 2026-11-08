"""Unit tests for automatic model catalog updater."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from ijachi_router.catalog_updater import (
    fetch_remote_catalog,
    get_cached_catalog_path,
    update_catalog,
)


def test_fetch_remote_catalog(monkeypatch):
    mock_data = {
        "data": [
            {
                "id": "openai/gpt-4o-mini",
                "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
                "context_length": 128000,
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: mock_resp)

    models = fetch_remote_catalog()
    assert len(models) == 1
    assert models[0]["model_id"] == "openai/gpt-4o-mini"
    assert models[0]["input_per_1k"] == 0.00015


def test_refresh_only_overlays_prices_on_curated_models(tmp_path, monkeypatch):
    from ijachi_router import catalog_updater, config
    monkeypatch.setattr(catalog_updater, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(catalog_updater, "_MODELS_CACHE_FILE", tmp_path / "models_cache.yaml")
    remote = [
        {"model_id": "openai/gpt-4o-mini", "input_per_1k": 0.0002, "output_per_1k": 0.0008, "max_context": 128000},
        {"model_id": "somevendor/brand-new-model", "input_per_1k": 0.1, "output_per_1k": 0.1, "max_context": 4096},
        {"model_id": "openrouter/auto", "input_per_1k": -1000.0, "output_per_1k": -1000.0, "max_context": 2000000},
    ]
    monkeypatch.setattr(catalog_updater, "fetch_remote_catalog", lambda: remote)
    ok, msg = catalog_updater.update_catalog()
    assert ok and "openai/gpt-4o-mini" in msg
    monkeypatch.setattr(config, "_detect_available_providers", lambda models: {"openai"})
    cfg = config.load_config()
    ids = {m.model_id for m in cfg.models}
    assert "somevendor/brand-new-model" not in ids and "brand-new-model" not in ids  # never adds models
    mini = next(m for m in cfg.models if m.provider == "openai" and m.model_id == "gpt-4o-mini")
    assert mini.input_per_1k == 0.0002 and mini.quality_tier == 2  # price refreshed, tier kept
    auto = next(m for m in cfg.models if m.model_id == "openrouter/auto")
    assert auto.input_per_1k >= 0  # placeholder (negative) prices are ignored


def test_update_catalog_caching(tmp_path, monkeypatch):
    test_cache_dir = tmp_path / ".ijachi-llmr"
    test_cache_file = test_cache_dir / "models_cache.yaml"
    monkeypatch.setattr("ijachi_router.catalog_updater._CACHE_DIR", test_cache_dir)
    monkeypatch.setattr("ijachi_router.catalog_updater._MODELS_CACHE_FILE", test_cache_file)

    mock_models = [{"model_id": "openai/gpt-4o-mini", "input_per_1k": 0.00015, "output_per_1k": 0.0006, "max_context": 128000}]

    monkeypatch.setattr("ijachi_router.catalog_updater.fetch_remote_catalog", lambda: mock_models)

    ok, msg = update_catalog(force=True)
    assert ok
    assert "Successfully updated" in msg
    assert test_cache_file.exists()
    assert get_cached_catalog_path() == test_cache_file
