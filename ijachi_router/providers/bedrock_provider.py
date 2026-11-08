"""AWS Bedrock provider implementation for enterprise cloud infrastructure."""

from __future__ import annotations

import os
from ijachi_router.providers.base import Provider, ProviderError


class BedrockProvider(Provider):
    """AWS Bedrock runtime provider wrapper using boto3 SDK."""

    name = "bedrock"
    native_tools = True

    def _converse_messages(self, prompt: str, kwargs: dict) -> list[dict]:
        if not self._use_native_tools(kwargs):
            return [{"role": m["role"], "content": [{"text": m["content"]}]} for m in self._conversation(prompt, kwargs)]
        out: list[dict] = []

        def push(role: str, blocks: list[dict]) -> None:
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": list(blocks)})

        for m in self._neutral(prompt, kwargs):
            if m.get("role") == "assistant":
                blocks = [{"text": str(m["content"])}] if m.get("content") else []
                blocks += [{"toolUse": {"toolUseId": c["id"], "name": c["name"], "input": c.get("args", {})}}
                           for c in m.get("tool_calls") or []]
                push("assistant", blocks or [{"text": "(no output)"}])
            elif m.get("role") == "tool":
                push("user", [{"toolResult": {"toolUseId": m["tool_call_id"], "content": [{"text": str(m.get("content", ""))}]}}])
            else:
                push("user", [{"text": str(m.get("content", "")) or "(empty)"}])
        if out and out[0]["role"] != "user":
            out.insert(0, {"role": "user", "content": [{"text": "(conversation resumed)"}]})
        return out

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not aws_key or not aws_secret:
            raise ProviderError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables must be set for AWS Bedrock."
            )

        try:
            import boto3
        except ImportError as e:
            raise ProviderError(
                "boto3 package is required for AWS Bedrock integration. Install with: pip install boto3"
            ) from e

        try:
            region = os.environ.get("AWS_REGION", "us-east-1")
            client = boto3.client("bedrock-runtime", region_name=region)

            # The Converse API works uniformly across Bedrock model families (Claude, Llama, ...).
            params: dict = {
                "modelId": self.model_id,
                "messages": self._converse_messages(prompt, kwargs),
                "inferenceConfig": {"maxTokens": self._max_tokens(kwargs)},
            }
            if kwargs.get("system"):
                params["system"] = [{"text": kwargs["system"]}]
            if self._use_native_tools(kwargs):
                params["toolConfig"] = {"tools": [
                    {"toolSpec": {"name": t["name"], "description": t.get("description", "") or t["name"],
                                  "inputSchema": {"json": t["parameters"]}}}
                    for t in kwargs["tools"]
                ]}
            response = client.converse(**params)

            parts = response.get("output", {}).get("message", {}).get("content", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p)
            calls = [
                {"id": p["toolUse"]["toolUseId"], "name": p["toolUse"]["name"], "args": p["toolUse"].get("input", {})}
                for p in parts if "toolUse" in p
            ]
            usage = response.get("usage", {})
            return text, usage.get("inputTokens", 0), usage.get("outputTokens", 0), calls
        except Exception as err:
            raise ProviderError(f"AWS Bedrock invocation failed for model '{self.model_id}': {err}") from err
