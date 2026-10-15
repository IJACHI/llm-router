import os

import requests

from ijachi_router.providers.base import Provider, ProviderError


class LocalProvider(Provider):
    """Talks to a local Ollama server. Free, private, no API key required."""

    name = "local"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            resp = requests.post(
                f"{host}/api/generate",
                json={"model": self.model_id, "prompt": prompt, "stream": False},
                timeout=kwargs.get("timeout", 120),
            )
            if resp.status_code == 404:
                try:
                    err_msg = resp.json().get("error", "")
                except Exception:
                    err_msg = ""
                if "not found" in err_msg.lower() or not err_msg:
                    raise ProviderError(
                        f"Model '{self.model_id}' not found on Ollama server at {host}. "
                        f"Please run `ollama pull {self.model_id}` to download it."
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
