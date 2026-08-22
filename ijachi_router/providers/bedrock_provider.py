"""AWS Bedrock provider implementation for enterprise cloud infrastructure."""

from __future__ import annotations

import json
import os
from ijachi_router.providers.base import Provider, ProviderError, _messages_with_system_prompt


class BedrockProvider(Provider):
    """AWS Bedrock runtime provider wrapper using boto3 SDK."""

    name = "bedrock"

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

            messages = _messages_with_system_prompt(prompt, **kwargs)
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": kwargs.get("max_tokens", 1024),
                "messages": messages,
            }

            response = client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(payload),
            )

            body = json.loads(response["body"].read().decode("utf-8"))
            text = body.get("content", [{}])[0].get("text", "")
            usage = body.get("usage", {})
            in_tokens = usage.get("input_tokens", 0)
            out_tokens = usage.get("output_tokens", 0)
            return text, in_tokens, out_tokens
        except Exception as err:
            raise ProviderError(f"AWS Bedrock invocation failed for model '{self.model_id}': {err}") from err

    def _ping(self) -> None:
        aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not aws_key or not aws_secret:
            raise ProviderError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set")
        try:
            import boto3
            region = os.environ.get("AWS_REGION", "us-east-1")
            client = boto3.client("bedrock", region_name=region)
            client.list_foundation_models(byOutputModality="TEXT")
        except Exception as err:
            raise ProviderError(f"AWS Bedrock connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not aws_key or not aws_secret:
            raise ProviderError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables must be set for AWS Bedrock."
            )
        try:
            import boto3
            region = os.environ.get("AWS_REGION", "us-east-1")
            client = boto3.client("bedrock-runtime", region_name=region)
            messages = _messages_with_system_prompt(prompt, **kwargs)
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": kwargs.get("max_tokens", 1024),
                "messages": messages,
            }
            response = client.invoke_model_with_response_stream(
                modelId=self.model_id,
                body=json.dumps(payload),
            )
            for event in response.get("body", []):
                chunk = json.loads(event["chunk"]["bytes"])
                if chunk.get("type") == "content_block_delta":
                    yield chunk.get("delta", {}).get("text", "")
        except Exception as err:
            raise ProviderError(f"AWS Bedrock streaming failed: {err}") from err
