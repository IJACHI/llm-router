import os

import requests

from ijachi_router.providers.base import Provider, ProviderError


class LocalProvider(Provider):
    """Talks to a local Ollama server. Free, private, no API key required."""

    name = "local"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        on_chunk = kwargs.get("on_stream_chunk")
        stream_mode = bool(on_chunk)
        try:
            resp = requests.post(
                f"{host}/api/generate",
                json={"model": self.model_id, "prompt": prompt, "stream": stream_mode},
                timeout=kwargs.get("timeout", 45),
                stream=stream_mode,
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

            if stream_mode:
                import json
                full_text = []
                in_tok = len(prompt.split())
                out_tok = 0
                for line in resp.iter_lines():
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        piece = chunk.get("response", "")
                        if piece:
                            full_text.append(piece)
                            on_chunk(piece)
                        if chunk.get("done"):
                            in_tok = chunk.get("prompt_eval_count", in_tok)
                            out_tok = chunk.get("eval_count", len(full_text))
                return "".join(full_text), in_tok, out_tok

        except requests.RequestException as e:
            raise ProviderError(f"could not reach Ollama at {host}: {e}") from e

        data = resp.json()
        text = data.get("response", "")
        # Ollama reports token counts in eval_count / prompt_eval_count
        in_tok = data.get("prompt_eval_count", len(prompt.split()))
        out_tok = data.get("eval_count", len(text.split()))
        return text, in_tok, out_tok
