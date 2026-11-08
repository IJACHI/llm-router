"""Shared adapter for every OpenAI-compatible Chat Completions endpoint.

Subclasses only declare how to authenticate and where the endpoint lives; request building,
native tool calling, streaming (text + tool-call deltas) and usage accounting live here.
"""

from __future__ import annotations

import os

from ijachi_router.providers.base import Provider, ProviderError


def _cached_tokens(usage) -> int:
    """Prompt tokens served from the provider's automatic prefix cache (OpenAI-style usage)."""
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    try:
        return int(getattr(details, "cached_tokens", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_reasoning_model(model_id: str) -> bool:
    """OpenAI o-series / gpt-5 reject `max_tokens` and expect `max_completion_tokens`."""
    return model_id.lower().startswith(("o1", "o3", "o4", "gpt-5"))


class OpenAICompatibleProvider(Provider):
    native_tools = True
    supports_streaming = True
    image_format = "openai"

    key_envs: tuple[str, ...] = ()
    key_error: str = ""
    base_url: str | None = None
    label: str = ""                  # used in wrapped error messages
    reasoning_quirks: bool = False   # apply o-series parameter rules (OpenAI/Azure only)

    # -- Hooks for subclasses ------------------------------------------------

    def _api_key(self) -> str:
        for env in self.key_envs:
            val = os.environ.get(env)
            if val:
                return val
        raise ProviderError(self.key_error or f"{' or '.join(self.key_envs)} not set")

    def _client(self, kwargs: dict):
        openai = self._openai()
        return openai.OpenAI(api_key=self._api_key(), base_url=self.base_url, timeout=self._timeout(kwargs))

    def _openai(self):
        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                f"openai package not installed (required for {self.label or self.name}). Run: pip install openai"
            ) from e
        return openai

    # -- Request ---------------------------------------------------------------

    def _params(self, prompt: str, kwargs: dict) -> dict:
        messages = self._chat_messages(prompt, kwargs)
        params: dict = {"model": self.model_id, "messages": messages, "timeout": self._timeout(kwargs)}
        if self.reasoning_quirks and _is_reasoning_model(self.model_id):
            params["max_completion_tokens"] = max(self._max_tokens(kwargs), 16_000)
            for m in messages:
                if m["role"] == "system":
                    m["role"] = "developer"
        else:
            params["max_tokens"] = self._max_tokens(kwargs)
        if self._use_native_tools(kwargs):
            params["tools"] = self._openai_tools(kwargs)
        return params

    def _call(self, prompt: str, **kwargs):
        client = self._client(kwargs)
        params = self._params(prompt, kwargs)
        on_delta = self._delta_cb(kwargs)
        try:
            if on_delta is not None:
                return self._stream(client, params, on_delta)
            resp = client.chat.completions.create(**params)
        except ProviderError:
            raise
        except Exception as err:
            if self.label:
                raise ProviderError(f"{self.label} call failed for model '{self.model_id}': {err}") from err
            raise

        msg = resp.choices[0].message
        text = msg.content or ""
        calls = [
            {"id": tc.id, "name": tc.function.name, "args": tc.function.arguments}
            for tc in (getattr(msg, "tool_calls", None) or [])
        ]
        usage = resp.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = usage.completion_tokens if usage else 0
        truncated = getattr(resp.choices[0], "finish_reason", None) == "length"
        return text, in_tok, out_tok, calls, {"cache_read": _cached_tokens(usage), "truncated": truncated}

    def _stream(self, client, params: dict, on_delta):
        try:
            stream = client.chat.completions.create(**params, stream=True, stream_options={"include_usage": True})
        except Exception as err:
            if "stream_options" not in str(err):
                raise
            stream = client.chat.completions.create(**params, stream=True)

        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        in_tok = out_tok = cached = 0
        truncated = False
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                in_tok = usage.prompt_tokens or in_tok
                out_tok = usage.completion_tokens or out_tok
                cached = _cached_tokens(usage) or cached
            if not getattr(chunk, "choices", None):
                continue
            if getattr(chunk.choices[0], "finish_reason", None) == "length":
                truncated = True
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                text_parts.append(piece)
                on_delta(piece)
            for tc in getattr(delta, "tool_calls", None) or []:
                slot = calls.setdefault(tc.index or 0, {"id": None, "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if fn.name:
                        slot["name"] += fn.name
                    if fn.arguments:
                        slot["args"] += fn.arguments
        text = "".join(text_parts)
        if not out_tok:
            out_tok = max(1, len(text) // 4 + sum(len(c["args"]) // 4 for c in calls.values()))
        if not in_tok:
            in_tok = sum(len(str(m.get("content") or "")) for m in params["messages"]) // 4
        ordered = [calls[i] for i in sorted(calls)]
        for c in ordered:
            if not c["id"]:
                c.pop("id")
        return text, in_tok, out_tok, ordered, {"cache_read": cached, "truncated": truncated}
