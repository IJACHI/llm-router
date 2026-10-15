"""Token estimator and counter for context assembly and budgeting.

Document 3.4:
Count tokens with provider tokenizers where available, otherwise conservative estimator.
"""

from __future__ import annotations


def estimate_tokens(text: str, provider: str = "default") -> int:
    """Return estimated token count for *text*.

    Uses tiktoken for OpenAI/Claude if available, otherwise conservative 3.8 chars/tok.
    """
    if not text:
        return 0

    try:
        if provider in ("openai", "azure", "cerebras", "sambanova", "groq"):
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
    except Exception:
        pass

    # Conservative estimator: average 3.8 chars per token
    return max(1, int(len(text) / 3.8))


def estimate_request_tokens(messages: list[dict], system_prompt: str = "") -> int:
    """Estimate total tokens for messages list and system prompt."""
    total = estimate_tokens(system_prompt)
    for m in messages:
        total += 4  # overhead per message
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(str(part.get("text", "")))
                else:
                    total += estimate_tokens(str(part))
    return total + 3  # priming tokens
