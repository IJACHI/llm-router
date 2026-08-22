import json
import os

import requests

from ijachi_router.providers.base import Provider, ProviderError


class LocalProvider(Provider):
    """Talks to a local Ollama server. Free, private, no API key required."""

    name = "local"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        # Retrieve Ollama host; ensure it includes a URL scheme.
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        try:
            resp = requests.post(
                f"{host}/api/generate",
                json={"model": self.model_id, "prompt": prompt, "stream": False},
                timeout=kwargs.get("timeout", 120),
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ProviderError(f"could not reach Ollama at {host}: {e}") from e

        data = resp.json()
        text = data.get("response", "")
        # Ollama reports token counts in eval_count / prompt_eval_count
        in_tok = data.get("prompt_eval_count", len(prompt.split()))
        out_tok = data.get("eval_count", len(text.split()))
        return text, in_tok, out_tok

    def _ping(self) -> None:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        try:
            resp = requests.get(f"{host}/api/tags", timeout=5)
            resp.raise_for_status()
        except Exception as err:
            raise ProviderError(f"could not reach Ollama at {host}: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        try:
            resp = requests.post(
                f"{host}/api/generate",
                json={"model": self.model_id, "prompt": prompt, "stream": True},
                stream=True,
                timeout=kwargs.get("timeout", 120),
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                yield data.get("response", "")
                if data.get("done"):
                    break
        except Exception as err:
            raise ProviderError(f"Ollama streaming failed: {err}") from err
