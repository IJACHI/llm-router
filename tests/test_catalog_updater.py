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


def test_update_catalog_caching(tmp_path, monkeypatch):
    test_cache_dir = tmp_path / ".ijachi-llmr"
    test_cache_file = test_cache_dir / "models_cache.yaml"
    monkeypatch.setattr("ijachi_router.catalog_updater._CACHE_DIR", test_cache_dir)
    monkeypatch.setattr("ijachi_router.catalog_updater._MODELS_CACHE_FILE", test_cache_file)

    mock_models = [
        {
            "provider": "openai",
            "model_id": "gpt-4o-mini",
            "tags": ["simple-qa"],
            "input_per_1k": 0.00015,
            "output_per_1k": 0.0006,
            "max_context": 128000,
            "speed_tier": "fast",
        }
    ]

    monkeypatch.setattr("ijachi_router.catalog_updater.fetch_remote_catalog", lambda: mock_models)

    ok, msg = update_catalog(force=True)
    assert ok
    assert "Updated pricing for" in msg
    assert "curated model" in msg
    assert test_cache_file.exists()
    assert get_cached_catalog_path() == test_cache_file
