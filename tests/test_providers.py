"""Unit tests for universal 20-provider registry and initialization."""

from __future__ import annotations

import pytest
from ijachi_router.providers import REGISTRY, ProviderError
from ijachi_router.providers.azure_provider import AzureOpenAIProvider
from ijachi_router.providers.bedrock_provider import BedrockProvider
from ijachi_router.providers.cerebras_provider import CerebrasProvider
from ijachi_router.providers.cohere_provider import CohereProvider
from ijachi_router.providers.custom_provider import CustomProvider
from ijachi_router.providers.deepseek_provider import DeepSeekProvider
from ijachi_router.providers.fireworks_provider import FireworksProvider
from ijachi_router.providers.gemini_provider import GeminiProvider
from ijachi_router.providers.groq_provider import GroqProvider
from ijachi_router.providers.huggingface_provider import HuggingFaceProvider
from ijachi_router.providers.mistral_provider import MistralProvider
from ijachi_router.providers.moonshot_provider import MoonshotProvider
from ijachi_router.providers.openrouter_provider import OpenRouterProvider
from ijachi_router.providers.perplexity_provider import PerplexityProvider
from ijachi_router.providers.qwen_provider import QwenProvider
from ijachi_router.providers.sambanova_provider import SambaNovaProvider
from ijachi_router.providers.together_provider import TogetherProvider


def test_registry_contains_all_20_providers():
    expected_providers = {
        "anthropic",
        "openai",
        "local",
        "deepseek",
        "gemini",
        "groq",
        "mistral",
        "together",
        "openrouter",
        "moonshot",
        "qwen",
        "perplexity",
        "cohere",
        "cerebras",
        "sambanova",
        "fireworks",
        "huggingface",
        "custom",
        "azure",
        "bedrock",
    }
    assert expected_providers == set(REGISTRY.keys())


def test_provider_missing_key_raises_error(monkeypatch):
    sample_pricing = {"input_per_1k": 0.001, "output_per_1k": 0.002}

    # Clear env keys
    for k in [
        "CEREBRAS_API_KEY",
        "SAMBANOVA_API_KEY",
        "FIREWORKS_API_KEY",
        "HF_TOKEN",
        "HUGGINGFACE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_ACCESS_KEY_ID",
    ]:
        monkeypatch.delenv(k, raising=False)

    p_cer = CerebrasProvider("llama3.1-70b", sample_pricing)
    with pytest.raises(ProviderError, match="CEREBRAS_API_KEY"):
        p_cer._call("hello")

    p_sam = SambaNovaProvider("Meta-Llama-3.1-405B-Instruct", sample_pricing)
    with pytest.raises(ProviderError, match="SAMBANOVA_API_KEY"):
        p_sam._call("hello")

    p_fw = FireworksProvider("llama-v3p1-70b-instruct", sample_pricing)
    with pytest.raises(ProviderError, match="FIREWORKS_API_KEY"):
        p_fw._call("hello")

    p_hf = HuggingFaceProvider("mistralai/Mistral-7B-Instruct-v0.3", sample_pricing)
    with pytest.raises(ProviderError, match="HF_TOKEN"):
        p_hf._call("hello")

    p_az = AzureOpenAIProvider("gpt-4o", sample_pricing)
    with pytest.raises(ProviderError, match="AZURE_OPENAI_API_KEY"):
        p_az._call("hello")

    p_bed = BedrockProvider("anthropic.claude-3-5-sonnet-v2:0", sample_pricing)
    with pytest.raises(ProviderError, match="AWS_ACCESS_KEY_ID"):
        p_bed._call("hello")
