"""Abstract provider interface. Every backend (OpenAI, Anthropic, local, ...)
implements this so the router core never has to know provider details.

Neutral request format (what callers pass through ``generate(prompt, **kwargs)``):

- ``system``: system prompt string
- ``messages``: chat history, provider-neutral:
      {"role": "user", "content": str}
      {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}   # tool_calls optional
      {"role": "tool", "tool_call_id": str, "name": str, "content": str}
  When omitted, a single user message built from ``prompt`` is sent.
- ``tools``: [{"name", "description", "parameters": <JSON schema>}] — native tool calling.
  Only honoured by adapters with ``native_tools = True``; others get a text rendering.
- ``on_text_delta``: callable(str) receiving streamed text as it is generated.
- ``max_tokens`` / ``timeout``

Adapters return ``(text, input_tokens, output_tokens)`` or, when the model made native tool
calls, ``(text, input_tokens, output_tokens, tool_calls)``.
"""

from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class GenerationResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    raw_error: str | None = None
    # Native tool calls: [{"id": str, "name": str, "args": dict}]
    tool_calls: list = field(default_factory=list)
    category: str | None = None
    streamed: bool = False
    cache_read_tokens: int = 0
    cache_saved_usd: float = 0.0
    truncated: bool = False  # output stopped at the token limit

    @property
    def model_used(self) -> str:
        return f"{self.provider}/{self.model}"

    @property
    def cost(self) -> float:
        return self.cost_usd

    @property
    def latency_sec(self) -> float:
        return self.latency_s


class ProviderError(Exception):
    """Raised when a provider call fails (timeout, auth, rate limit, etc)."""


class ToolsUnsupportedError(ProviderError):
    """The model/endpoint rejected native tool definitions; retry in text mode."""


DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_S = 120.0

_TOOLS_REJECTION_HINTS = (
    "does not support tools", "tools is not supported", "tool use is not supported",
    "function calling is not", "tool_choice", "tools are not supported", "unsupported parameter: 'tools'",
    "unrecognized request argument supplied: tools", "does not support function", "tool calling",
)


def looks_like_tools_rejection(err: Exception) -> bool:
    msg = str(err).lower()
    return any(h in msg for h in _TOOLS_REJECTION_HINTS)


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


def render_text_tool_call(call: dict, thought: str = "") -> str:
    """The JSON-in-text format text-mode models are instructed to emit."""
    payload = {"thought": thought, "tool": call.get("name"), "args": call.get("args", {})}
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def parse_tool_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {"value": val}
    except (TypeError, ValueError):
        return {"_raw_arguments": str(raw)}


class Provider(ABC):
    """Base provider. See module docstring for the neutral request format."""

    name: str = "base"
    native_tools: bool = False
    supports_streaming: bool = False
    # Price of cached input relative to normal input (1.0 = no discount assumed).
    cache_read_multiplier: float = 1.0
    cache_write_multiplier: float = 1.0
    # How this adapter sends images in user messages: "openai", "anthropic" or None (unsupported).
    image_format: str | None = None

    def __init__(self, model_id: str, pricing: dict):
        self.model_id = model_id
        self.pricing = pricing  # {"input_per_1k": float, "output_per_1k": float}

    # -- Message conversion --------------------------------------------------

    @staticmethod
    def _neutral(prompt: str, kwargs: dict) -> list[dict]:
        return list(kwargs.get("messages") or [{"role": "user", "content": prompt}])

    def _use_native_tools(self, kwargs: dict) -> bool:
        return bool(self.native_tools and kwargs.get("tools"))

    @staticmethod
    def split_content(content: Any) -> tuple[str, list[dict]]:
        """(text, images) from neutral content: a string or [{"type": "text"|"image", ...}]."""
        if isinstance(content, str) or content is None:
            return content or "", []
        texts, images = [], []
        for part in content:
            if part.get("type") == "image":
                images.append(part)
            else:
                texts.append(str(part.get("text", "")))
        return "\n".join(texts), images

    @staticmethod
    def image_parts(text: str, images: list[dict], fmt: str) -> list[dict]:
        if fmt == "anthropic":
            parts = [{"type": "image", "source": {"type": "base64", "media_type": i["media_type"], "data": i["data"]}} for i in images]
            return parts + [{"type": "text", "text": text or "(see image)"}]
        return [{"type": "text", "text": text or "(see image)"}] + [
            {"type": "image_url", "image_url": {"url": f"data:{i['media_type']};base64,{i['data']}"}} for i in images
        ]

    def _user_content(self, content: Any) -> Any:
        """Wire content for a user message: plain text, or parts when images are attached."""
        text, images = self.split_content(content)
        if not images:
            return text
        if self.image_format:
            return self.image_parts(text, images, self.image_format)
        return text + f"\n[{len(images)} image(s) attached, but this model cannot view images]"

    def _text_conversation(self, messages: list[dict]) -> list[dict]:
        """Render neutral messages as plain user/assistant text turns (merged, user first)."""
        merged: list[dict] = []

        def add(role: str, content: Any) -> None:
            if isinstance(content, list) or (merged and isinstance(merged[-1]["content"], list)):
                merged.append({"role": role, "content": content})  # image turns are never merged
            elif merged and merged[-1]["role"] == role:
                merged[-1]["content"] += "\n\n" + content
            else:
                merged.append({"role": role, "content": content})

        for m in messages:
            role = m.get("role")
            if role == "assistant":
                parts = [str(m.get("content") or "")] if m.get("content") else []
                for call in m.get("tool_calls") or []:
                    parts.append(render_text_tool_call(call, call.get("thought", "")))
                add("assistant", "\n\n".join(parts) or "(no output)")
            elif role == "tool":
                add("user", str(m.get("content", "")))
            else:
                add("user", self._user_content(m.get("content", "")))
        if merged and merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "(conversation resumed)"})
        return merged

    def _conversation(self, prompt: str, kwargs: dict) -> list[dict]:
        """Plain text chat turns (no system message)."""
        return self._text_conversation(self._neutral(prompt, kwargs))

    def _chat_messages(self, prompt: str, kwargs: dict) -> list[dict]:
        """OpenAI-style message list (system first); native tool messages when enabled."""
        neutral = self._neutral(prompt, kwargs)
        if self._use_native_tools(kwargs):
            msgs: list[dict] = []
            for m in neutral:
                role = m.get("role")
                if role == "assistant" and m.get("tool_calls"):
                    msgs.append({
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))},
                            }
                            for c in m["tool_calls"]
                        ],
                    })
                elif role == "tool":
                    msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": str(m.get("content", ""))})
                elif role == "assistant":
                    msgs.append({"role": "assistant", "content": str(m.get("content") or "")})
                else:
                    content = self._user_content(m.get("content", ""))
                    if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], str) and isinstance(content, str):
                        msgs[-1]["content"] += "\n\n" + content
                    else:
                        msgs.append({"role": "user", "content": content})
            if msgs and msgs[0]["role"] != "user":
                msgs.insert(0, {"role": "user", "content": "(conversation resumed)"})
        else:
            msgs = self._text_conversation(neutral)
        system = kwargs.get("system")
        if system:
            msgs = [{"role": "system", "content": system}, *msgs]
        return msgs

    @staticmethod
    def _openai_tools(kwargs: dict) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"]}}
            for t in kwargs.get("tools") or []
        ]

    @staticmethod
    def _max_tokens(kwargs: dict) -> int:
        return int(kwargs.get("max_tokens") or DEFAULT_MAX_TOKENS)

    @staticmethod
    def _timeout(kwargs: dict) -> float:
        return float(kwargs.get("timeout") or DEFAULT_TIMEOUT_S)

    @staticmethod
    def _delta_cb(kwargs: dict) -> Callable[[str], None] | None:
        return kwargs.get("on_text_delta")

    # -- Call ----------------------------------------------------------------

    @abstractmethod
    def _call(self, prompt: str, **kwargs) -> tuple:
        """Return (text, in_tokens, out_tokens[, tool_calls]). Raise ProviderError on failure."""
        raise NotImplementedError

    def generate(self, prompt: str, **kwargs) -> GenerationResult:
        start = time.monotonic()
        streamed = False
        user_cb = kwargs.get("on_text_delta")
        if user_cb is not None:
            def _cb(piece: str) -> None:
                nonlocal streamed
                if piece:
                    streamed = True
                    user_cb(piece)
            kwargs["on_text_delta"] = _cb
        try:
            out = self._call(prompt, **kwargs)
        except ToolsUnsupportedError:
            raise
        except Exception as e:  # noqa: BLE001 - normalize all provider failures
            if kwargs.get("tools") and looks_like_tools_rejection(e):
                raise ToolsUnsupportedError(f"{self.name}/{self.model_id}: {e}") from e
            raise ProviderError(f"{self.name}/{self.model_id}: {e}") from e
        text, in_tok, out_tok = out[0], out[1], out[2]
        tool_calls = list(out[3]) if len(out) > 3 and out[3] else []
        usage_extra = out[4] if len(out) > 4 and out[4] else {}
        cache_read = int(usage_extra.get("cache_read", 0) or 0)
        cache_write = int(usage_extra.get("cache_write", 0) or 0)
        for c in tool_calls:
            c.setdefault("id", new_call_id())
            c["args"] = parse_tool_arguments(c.get("args"))
        latency = time.monotonic() - start
        in_price = self.pricing.get("input_per_1k", 0) / 1000
        uncached = max(0, in_tok - cache_read - cache_write)
        cost = (
            uncached * in_price
            + cache_read * in_price * self.cache_read_multiplier
            + cache_write * in_price * self.cache_write_multiplier
            + (out_tok / 1000) * self.pricing.get("output_per_1k", 0)
        )
        saved = cache_read * in_price * (1 - self.cache_read_multiplier)
        return GenerationResult(
            text=text or "",
            provider=self.name,
            model=self.model_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
            latency_s=round(latency, 3),
            tool_calls=tool_calls,
            streamed=streamed,
            cache_read_tokens=cache_read,
            cache_saved_usd=round(max(0.0, saved), 6),
            truncated=bool(usage_extra.get("truncated")),
        )
