import os

from ijachi_router.providers.base import Provider, ProviderError


class AnthropicProvider(Provider):
    name = "anthropic"
    native_tools = True
    supports_streaming = True
    image_format = "anthropic"
    cache_read_multiplier = 0.1     # cache reads bill at 10% of input
    cache_write_multiplier = 1.25   # 5-minute cache writes bill at 125%

    def _messages(self, prompt: str, kwargs: dict) -> list[dict]:
        """Neutral messages -> Anthropic content blocks (tool_use / tool_result when native)."""
        if not self._use_native_tools(kwargs):
            return self._conversation(prompt, kwargs)
        out: list[dict] = []

        def push(role: str, blocks: list[dict]) -> None:
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": list(blocks)})

        for m in self._neutral(prompt, kwargs):
            role = m.get("role")
            if role == "assistant":
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": str(m["content"])})
                for c in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("args", {})})
                push("assistant", blocks or [{"type": "text", "text": "(no output)"}])
            elif role == "tool":
                push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": str(m.get("content", ""))}])
            else:
                content = self._user_content(m.get("content", ""))
                push("user", content if isinstance(content, list) else [{"type": "text", "text": content or "(empty)"}])
        if out and out[0]["role"] != "user":
            out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(conversation resumed)"}]})
        # Tool results must lead the user turn that answers a tool_use.
        for msg in out:
            if msg["role"] == "user":
                msg["content"].sort(key=lambda b: 0 if b["type"] == "tool_result" else 1)
        return out

    def _call(self, prompt: str, **kwargs):
        try:
            import anthropic
        except ImportError as e:
            raise ProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")

        timeout_sec = self._timeout(kwargs)
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout_sec)
        params: dict = {
            "model": self.model_id,
            # Current Claude models think before answering and thinking counts toward
            # max_tokens; leave headroom so the visible answer is not cut off.
            "max_tokens": max(self._max_tokens(kwargs), 16_000),
            "messages": self._messages(prompt, kwargs),
            "timeout": timeout_sec,
            # Automatic caching of the conversation prefix: agent loops resend the same
            # history every step, so later steps read it from cache.
            "cache_control": {"type": "ephemeral"},
        }
        if kwargs.get("system"):
            # Cache the (large, stable) system prompt across agent iterations.
            params["system"] = [
                {"type": "text", "text": kwargs["system"], "cache_control": {"type": "ephemeral"}}
            ]
        if self._use_native_tools(kwargs):
            params["tools"] = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]}
                for t in kwargs["tools"]
            ]

        on_delta = self._delta_cb(kwargs)
        if on_delta is not None:
            with client.messages.stream(**params) as stream:
                for piece in stream.text_stream:
                    on_delta(piece)
                resp = stream.get_final_message()
        else:
            resp = client.messages.create(**params)

        if getattr(resp, "stop_reason", None) == "refusal":
            # Raise so the router falls back to the next candidate model.
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(f"request declined by {self.model_id} (category: {category or 'unspecified'})")

        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        calls = [
            {"id": block.id, "name": block.name, "args": dict(block.input or {})}
            for block in resp.content
            if getattr(block, "type", None) == "tool_use"
        ]
        usage = resp.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        in_tok = usage.input_tokens + cache_read + cache_write
        truncated = getattr(resp, "stop_reason", None) == "max_tokens"
        return text, in_tok, usage.output_tokens, calls, {"cache_read": cache_read, "cache_write": cache_write, "truncated": truncated}
