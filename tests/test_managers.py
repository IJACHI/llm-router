"""Unit tests for ModelManager and KeyManager."""

from __future__ import annotations

from pathlib import Path
import pytest

from ijachi_router.key_manager import KeyManager, mask_secret
from ijachi_router.model_manager import ModelManager


def test_mask_secret():
    assert mask_secret("sk-ant-1234567890abcdef") == "sk-ant***cdef"
    assert mask_secret("short") == "*****"


def test_key_manager_lifecycle(tmp_path):
    keys_file = tmp_path / "keys.env"
    km = KeyManager(keys_file=keys_file)

    # Set key
    msg = km.set_key("anthropic", "sk-ant-testkey123456")
    assert "anthropic" in msg
    assert km.get_key("anthropic") == "sk-ant-testkey123456"

    # List keys
    keys = km.list_keys()
    assert "anthropic" in keys
    assert "sk-ant***3456" in keys["anthropic"]

    # Clear key
    msg_clear = km.clear_key("anthropic")
    assert "cleared" in msg_clear.lower()
    assert km.get_key("anthropic") is None


def test_model_manager(tmp_path):
    models_yaml = tmp_path / "models.yaml"
    models_yaml.write_text(
        "version: '1.0'\ndefault_priority: balanced\nmodels:\n"
        "  - model_id: gpt-4o\n    provider: openai\n    speed_tier: fast\n    input_per_1k: 0.001\n    output_per_1k: 0.002\n    tags: [simple-qa, code]\n",
        encoding="utf-8",
    )

    mm = ModelManager(models_yaml=models_yaml)
    models = mm.list_models()
    assert len(models) == 1
    assert models[0].model_id == "gpt-4o"

    msg = mm.add_model("claude-3-7-sonnet", "anthropic", speed_tier="slow", input_per_1k=0.003, output_per_1k=0.015)
    assert "added" in msg.lower()

    models_updated = mm.list_models()
    assert len(models_updated) == 2
    assert any(m.model_id == "claude-3-7-sonnet" for m in models_updated)
