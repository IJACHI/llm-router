"""Prompt optimizer: rule-based per-provider prompt rewrites.

Design decision: NO LLM call is made here. These are purely string
transformations applied once the router has picked a target provider.
Keeping this fast and free is essential to the cost-saving pitch.
"""

from __future__ import annotations


_REASONING_CATEGORIES = {"reasoning", "math", "code"}
_CREATIVE_CATEGORIES = {"creative"}
_LONG_CATEGORIES = {"long-context"}


def _optimize_anthropic(prompt: str, category: str) -> str:
    """Anthropic models respond well to XML-ish structure and chain-of-thought."""
    wrapped = f"<task>\n{prompt.strip()}\n</task>"
    if category in _REASONING_CATEGORIES:
        wrapped += "\n\n<instructions>Think step by step before giving your final answer.</instructions>"
    if category in _LONG_CATEGORIES:
        wrapped += "\n\n<instructions>Read the entire input carefully before responding. Be thorough and systematic.</instructions>"
    return wrapped


def _optimize_openai(prompt: str, category: str) -> str:
    """OpenAI models respond well to a clear system-style framing prefix."""
    if category == "code":
        preamble = "You are an expert software engineer. Provide clean, well-commented code with brief explanations."
    elif category == "math":
        preamble = "You are a precise mathematics expert. Show your work step by step."
    elif category == "creative":
        preamble = "You are a skilled creative writer. Produce vivid, engaging content."
    elif category == "summarization":
        preamble = "You are a concise editor. Provide clear, accurate summaries."
    elif category == "reasoning":
        preamble = "You are an analytical expert. Reason carefully and consider multiple perspectives."
    elif category == "long-context":
        preamble = "You are a careful analyst. Read all provided content before responding."
    else:
        preamble = "Answer the following question directly and accurately."
    return f"{preamble}\n\n{prompt.strip()}"


def _optimize_local(prompt: str, category: str) -> str:
    """Local / Ollama models (usually smaller) need concise, focused prompts."""
    core = prompt.strip()
    if category == "code":
        suffix = "\n\nRespond with code only, then a brief explanation."
    elif category == "math":
        suffix = "\n\nShow your working, then state the final answer clearly."
    elif category == "creative":
        suffix = "\n\nBe concise and creative. Keep the response under 200 words."
    elif category == "summarization":
        suffix = "\n\nRespond with bullet points. Be concise."
    elif category in {"reasoning", "long-context"}:
        suffix = "\n\nThink step by step. Give a clear, direct answer."
    else:
        suffix = "\n\nAnswer directly and concisely."
    return core + suffix


def _optimize_deepseek(prompt: str, category: str) -> str:
    """DeepSeek models excel at reasoning and code when guided with explicit steps."""
    if category in _REASONING_CATEGORIES:
        return f"Please solve the following task with rigorous step-by-step reasoning:\n\n{prompt.strip()}"
    return f"Provide a clean, precise answer to the following request:\n\n{prompt.strip()}"


def _optimize_gemini(prompt: str, category: str) -> str:
    """Gemini models handle large context and multimodal/structured prompts effectively."""
    return f"[Task: {category.upper()}]\n{prompt.strip()}\n\nPlease respond clearly and accurately."


def _optimize_groq(prompt: str, category: str) -> str:
    """Groq ultra-fast LPU inference works best with direct, unadorned prompts."""
    return f"System: Direct, fast, accurate output.\nTask: {prompt.strip()}"


def _optimize_mistral(prompt: str, category: str) -> str:
    """Mistral models work best with technical precision and structured formatting."""
    return f"[INST] {prompt.strip()} [/INST]"


_OPTIMIZERS = {
    "anthropic": _optimize_anthropic,
    "openai": _optimize_openai,
    "local": _optimize_local,
    "deepseek": _optimize_deepseek,
    "gemini": _optimize_gemini,
    "groq": _optimize_groq,
    "mistral": _optimize_mistral,
    "together": _optimize_openai,
    "openrouter": _optimize_openai,
    "moonshot": _optimize_openai,
    "qwen": _optimize_openai,
    "perplexity": _optimize_openai,
    "cohere": _optimize_openai,
    "cerebras": _optimize_openai,
    "sambanova": _optimize_openai,
    "fireworks": _optimize_openai,
    "huggingface": _optimize_openai,
    "custom": _optimize_openai,
    "azure": _optimize_openai,
    "bedrock": _optimize_anthropic,
}


def is_agentic_prompt(prompt: str) -> bool:
    """Check if prompt contains structured agentic tool directives."""
    indicators = (
        "ijachi-code",
        "write_file",
        "read_file",
        "edit_file",
        "list_dir",
        "grep_search",
        "run_command",
        "```json",
        '"tool":',
        "--- IJACHI CONTEXT & PERSISTENT MEMORY ---",
    )
    return any(ind in prompt for ind in indicators)


def optimize_prompt(prompt: str, provider: str, category: str = "simple-qa") -> str:
    """Return an optimized version of *prompt* for *provider*."""
    # Never mutate or append conversational suffixes to agentic/tool-calling prompts
    if is_agentic_prompt(prompt):
        return prompt
    optimizer = _OPTIMIZERS.get(provider)
    if optimizer is None:
        return prompt
    return optimizer(prompt, category)
