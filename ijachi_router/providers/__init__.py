from ijachi_router.providers.anthropic_provider import AnthropicProvider
from ijachi_router.providers.azure_provider import AzureOpenAIProvider
from ijachi_router.providers.base import GenerationResult, Provider, ProviderError
from ijachi_router.providers.bedrock_provider import BedrockProvider
from ijachi_router.providers.cerebras_provider import CerebrasProvider
from ijachi_router.providers.cohere_provider import CohereProvider
from ijachi_router.providers.custom_provider import CustomProvider
from ijachi_router.providers.deepseek_provider import DeepSeekProvider
from ijachi_router.providers.fireworks_provider import FireworksProvider
from ijachi_router.providers.gemini_provider import GeminiProvider
from ijachi_router.providers.groq_provider import GroqProvider
from ijachi_router.providers.huggingface_provider import HuggingFaceProvider
from ijachi_router.providers.local_provider import LocalProvider
from ijachi_router.providers.mistral_provider import MistralProvider
from ijachi_router.providers.moonshot_provider import MoonshotProvider
from ijachi_router.providers.openai_provider import OpenAIProvider
from ijachi_router.providers.openrouter_provider import OpenRouterProvider
from ijachi_router.providers.perplexity_provider import PerplexityProvider
from ijachi_router.providers.qwen_provider import QwenProvider
from ijachi_router.providers.sambanova_provider import SambaNovaProvider
from ijachi_router.providers.together_provider import TogetherProvider

REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "local": LocalProvider,
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "mistral": MistralProvider,
    "together": TogetherProvider,
    "openrouter": OpenRouterProvider,
    "moonshot": MoonshotProvider,
    "qwen": QwenProvider,
    "perplexity": PerplexityProvider,
    "cohere": CohereProvider,
    "cerebras": CerebrasProvider,
    "sambanova": SambaNovaProvider,
    "fireworks": FireworksProvider,
    "huggingface": HuggingFaceProvider,
    "custom": CustomProvider,
    "azure": AzureOpenAIProvider,
    "bedrock": BedrockProvider,
}

__all__ = [
    "REGISTRY",
    "Provider",
    "ProviderError",
    "GenerationResult",
    "AnthropicProvider",
    "OpenAIProvider",
    "LocalProvider",
    "DeepSeekProvider",
    "GeminiProvider",
    "GroqProvider",
    "MistralProvider",
    "TogetherProvider",
    "OpenRouterProvider",
    "MoonshotProvider",
    "QwenProvider",
    "PerplexityProvider",
    "CohereProvider",
    "CerebrasProvider",
    "SambaNovaProvider",
    "FireworksProvider",
    "HuggingFaceProvider",
    "CustomProvider",
    "AzureOpenAIProvider",
    "BedrockProvider",
]
