"""Smart Model Benchmarker for ijachi-llm-router.

Runs standardized benchmark prompts across active providers to measure real-world
latency, token generation speed (tok/s), accuracy, and cost per call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ijachi_router.config import load_config
from ijachi_router.core import _build_provider


@dataclass
class BenchmarkResult:
    provider: str
    model: str
    latency_sec: float
    tokens_per_sec: float
    output_tokens: int
    cost_usd: float
    status: str  # success | error
    error_msg: str | None = None


class BenchmarkEngine:
    """Runs performance benchmarks across all configured provider models."""

    BENCHMARK_PROMPTS = {
        "code": "Write a Python function to check if a string is a palindrome.",
        "reasoning": "Explain the trade-offs between SQL and NoSQL databases.",
        "speed": "Count from 1 to 5.",
    }

    def run_benchmark(self, prompt_category: str = "code") -> list[BenchmarkResult]:
        config = load_config()
        results: list[BenchmarkResult] = []

        prompt = self.BENCHMARK_PROMPTS.get(prompt_category, self.BENCHMARK_PROMPTS["code"])

        for model_cfg in config.models:
            if model_cfg.provider not in config.available_providers:
                continue

            try:
                provider_inst = _build_provider(model_cfg)
            except Exception:
                continue

            start_t = time.monotonic()
            try:
                res = provider_inst.generate(prompt)
                latency = time.monotonic() - start_t
                tok_per_sec = res.output_tokens / max(latency, 0.001)

                results.append(
                    BenchmarkResult(
                        provider=res.provider,
                        model=res.model,
                        latency_sec=round(latency, 3),
                        tokens_per_sec=round(tok_per_sec, 1),
                        output_tokens=res.output_tokens,
                        cost_usd=res.cost_usd,
                        status="success",
                    )
                )
            except Exception as e:
                latency = time.monotonic() - start_t
                results.append(
                    BenchmarkResult(
                        provider=model_cfg.provider,
                        model=model_cfg.model_id,
                        latency_sec=round(latency, 3),
                        tokens_per_sec=0.0,
                        output_tokens=0,
                        cost_usd=0.0,
                        status="error",
                        error_msg=str(e),
                    )
                )

        return results

    def format_table(self, results: list[BenchmarkResult]) -> str:
        if not results:
            return "No active providers configured to benchmark."

        lines = [
            f"\n{'Provider':<15} {'Model':<25} {'Latency(s)':<12} {'Speed(tok/s)':<15} {'Cost($)':<10} {'Status':<10}",
            "-" * 87,
        ]

        for r in results:
            if r.status == "success":
                lines.append(
                    f"{r.provider:<15} {r.model:<25} {r.latency_sec:<12.3f} {r.tokens_per_sec:<15.1f} ${r.cost_usd:<9.4f} ✓ ok"
                )
            else:
                lines.append(
                    f"{r.provider:<15} {r.model:<25} {r.latency_sec:<12.3f} {'0.0':<15} {'$0.0000':<10} ✗ error"
                )

        return "\n".join(lines) + "\n"
