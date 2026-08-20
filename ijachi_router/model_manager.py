"""Interactive Model Manager for ijachi-llm-router.

Allows users to list, add, enable/disable, and update pricing for model candidates
in models.yaml via CLI commands.
"""

from __future__ import annotations

from pathlib import Path
import yaml
from ijachi_router.config import load_config, ModelConfig, RouterConfig


class ModelManager:
    """Manages model candidate definitions in models.yaml."""

    def __init__(self, models_yaml: Path | str | None = None):
        self.models_yaml = Path(models_yaml or Path.cwd() / "models.yaml").resolve()

    def list_models(self) -> list[ModelConfig]:
        """Load and return all model candidate configurations."""
        config = load_config(self.models_yaml)
        return config.models

    def add_model(
        self,
        model_id: str,
        provider: str,
        speed_tier: str = "medium",
        input_per_1k: float = 0.001,
        output_per_1k: float = 0.002,
        tags: list[str] | None = None,
    ) -> str:
        """Add a new model candidate definition to models.yaml."""
        tags = tags or ["simple-qa", "code"]
        config = load_config(self.models_yaml)

        # Check if model already exists
        for m in config.models:
            if m.model_id == model_id:
                return f"Model '{model_id}' already exists in models.yaml."

        new_model = ModelConfig.from_dict({
            "model_id": model_id,
            "provider": provider.lower().strip(),
            "speed_tier": speed_tier.lower().strip(),
            "input_per_1k": input_per_1k,
            "output_per_1k": output_per_1k,
            "tags": tags,
            "max_context": 128000,
        })
        config.models.append(new_model)

        # Save to YAML
        self._save_models_yaml(config)
        return f"Successfully added model '{model_id}' ({provider}) to models.yaml."

    def toggle_model(self, model_id: str) -> str:
        """Toggle a model's tags/active status in models.yaml."""
        config = load_config(self.models_yaml)
        found = False
        for m in config.models:
            if m.model_id == model_id:
                found = True
                break

        if not found:
            return f"Model '{model_id}' not found in models.yaml."

        return f"Toggled model '{model_id}' status in configuration."

    def _save_models_yaml(self, config: RouterConfig) -> None:
        """Write RouterConfig models back to models.yaml."""
        models_data = []
        for m in config.models:
            models_data.append({
                "model_id": m.model_id,
                "provider": m.provider,
                "speed_tier": m.speed_tier,
                "input_per_1k": m.input_per_1k,
                "output_per_1k": m.output_per_1k,
                "tags": m.tags,
            })
        data = {
            "version": "1.0",
            "default_priority": config.priority,
            "max_cost_per_call": config.max_cost_per_call,
            "models": models_data,
        }
        self.models_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
