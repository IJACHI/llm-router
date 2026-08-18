"""Example: basic usage of ijachi-llm-router as a Python library.

Before running, ensure at least one provider is configured:
  - Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment
  - Or have Ollama running locally with a model pulled

Usage:
    python examples/basic_usage.py
"""

from ijachi_router import route, Router
from ijachi_router.providers.base import ProviderError


def main():
    # ── Simple one-shot routing ──────────────────────────────────────────────
    print("=== One-shot routing ===\n")
    try:
        result = route("What is the capital of Japan?")
        print(f"Response: {result.text}")
        print(f"Model:    {result.model}")
        print(f"Cost:     ${result.cost_usd:.4f}")
        print(f"Latency:  {result.latency_s:.2f}s")
        print(f"Tokens:   {result.input_tokens} in / {result.output_tokens} out")
    except ProviderError as e:
        print(f"Error: {e}")

    # ── Cost-optimized routing ───────────────────────────────────────────────
    print("\n=== Cost-optimized routing ===\n")
    try:
        router = Router()
        router.config.priority = "cost"
        result = router.route("Explain what a hash map is")
        print(f"Response: {result.text[:100]}...")
        print(f"Model:    {result.model} (cheapest available)")
        print(f"Cost:     ${result.cost_usd:.4f}")
    except ProviderError as e:
        print(f"Error: {e}")

    # ── Quality-first routing ────────────────────────────────────────────────
    print("\n=== Quality-first routing ===\n")
    try:
        router = Router()
        router.config.priority = "quality"
        result = router.route("Prove that the square root of 2 is irrational")
        print(f"Response: {result.text[:200]}...")
        print(f"Model:    {result.model} (strongest available)")
        print(f"Cost:     ${result.cost_usd:.4f}")
    except ProviderError as e:
        print(f"Error: {e}")

    # ── Check available providers ────────────────────────────────────────────
    print("\n=== Available providers ===\n")
    router = Router()
    print(f"Configured providers: {', '.join(sorted(router.config.available_providers))}")
    print(f"Total models:         {len(router.config.models)}")
    print(f"Available models:     {len(router.config.available_models())}")


if __name__ == "__main__":
    main()
