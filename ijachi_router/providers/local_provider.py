import json
import os
import time

import requests

from ijachi_router.providers.base import Provider, ProviderError

# Ollama defaults to a 2048-token context and silently truncates the front of longer prompts,
# which would drop the agent system prompt. Ask for a window large enough for agent turns.
_DEFAULT_NUM_CTX = int(os.environ.get("IJACHI_OLLAMA_NUM_CTX", "16384"))

_PULLED_CACHE: tuple[float, set[str] | None] = (0.0, None)
_PULLED_TTL_S = 30.0


def ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def list_pulled_models(timeout: float = 0.5) -> set[str] | None:
    """Return model names pulled into the local Ollama server, or None if it is unreachable.

    Cached briefly so routing does not probe the server on every model request.
    """
    global _PULLED_CACHE
    ts, cached = _PULLED_CACHE
    if time.monotonic() - ts < _PULLED_TTL_S:
        return cached
    try:
        resp = requests.get(f"{ollama_host()}/api/tags", timeout=timeout)
        resp.raise_for_status()
        names: set[str] = set()
        for m in resp.json().get("models", []):
            name = m.get("name") or m.get("model") or ""
            if name:
                names.add(name)
                if name.endswith(":latest"):
                    names.add(name[: -len(":latest")])
        result: set[str] | None = names
    except Exception:
        result = None
    _PULLED_CACHE = (time.monotonic(), result)
    return result


class LocalProvider(Provider):
    """Talks to a local Ollama server. Free, private, no API key required."""

    name = "local"
    native_tools = True
    supports_streaming = True
    image_format = "openai"  # converted to Ollama's {"images": [...]} below

    def _ollama_messages(self, prompt: str, kwargs: dict) -> list[dict]:
        msgs = self._chat_messages(prompt, kwargs)
        for m in msgs:
            if isinstance(m.get("content"), list):  # images -> Ollama format
                parts = m["content"]
                m["content"] = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
                m["images"] = [p["image_url"]["url"].split(",", 1)[1] for p in parts if p.get("type") == "image_url"]
        if not self._use_native_tools(kwargs):
            return msgs
        # Ollama wants tool-call arguments as objects, not JSON strings.
        for m in msgs:
            for tc in m.get("tool_calls") or []:
                fn = tc["function"]
                fn["arguments"] = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                tc.pop("id", None)
                tc.pop("type", None)
            if m.get("role") == "tool":
                m.pop("tool_call_id", None)
            if m.get("content") is None:
                m["content"] = ""
        return msgs

    def _call(self, prompt: str, **kwargs):
        host = ollama_host()
        on_delta = self._delta_cb(kwargs)
        stream_mode = on_delta is not None
        payload = {
            "model": self.model_id,
            "messages": self._ollama_messages(prompt, kwargs),
            "stream": stream_mode,
            "options": {"num_ctx": _DEFAULT_NUM_CTX, "num_predict": self._max_tokens(kwargs)},
        }
        if self._use_native_tools(kwargs):
            payload["tools"] = self._openai_tools(kwargs)
        try:
            resp = requests.post(
                f"{host}/api/chat",
                json=payload,
                timeout=self._timeout(kwargs),
                stream=stream_mode,
            )
            if resp.status_code == 404:
                raise ProviderError(
                    f"Model '{self.model_id}' not found on Ollama server at {host}. "
                    f"Run `ollama pull {self.model_id}` to download it."
                )
            if resp.status_code == 400:
                try:
                    err = resp.json().get("error", "")
                except Exception:
                    err = resp.text
                raise ProviderError(f"Ollama rejected the request: {err}")
            resp.raise_for_status()

            calls: list[dict] = []
            if stream_mode:
                full_text: list[str] = []
                in_tok = len(prompt.split())
                out_tok = 0
                truncated = False
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line.decode("utf-8"))
                    msg = chunk.get("message", {})
                    piece = msg.get("content", "")
                    if piece:
                        full_text.append(piece)
                        on_delta(piece)
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function", {})
                        calls.append({"name": fn.get("name", ""), "args": fn.get("arguments", {})})
                    if chunk.get("done"):
                        in_tok = chunk.get("prompt_eval_count", in_tok)
                        out_tok = chunk.get("eval_count", len(full_text))
                        truncated = chunk.get("done_reason") == "length"
                return "".join(full_text), in_tok, out_tok, calls, {"truncated": truncated}

            data = resp.json()
        except requests.RequestException as e:
            raise ProviderError(f"could not reach Ollama at {host}: {e}") from e

        msg = data.get("message", {})
        text = msg.get("content", "")
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            calls.append({"name": fn.get("name", ""), "args": fn.get("arguments", {})})
        in_tok = data.get("prompt_eval_count", len(prompt.split()))
        out_tok = data.get("eval_count", len(text.split()))
        return text, in_tok, out_tok, calls, {"truncated": data.get("done_reason") == "length"}
