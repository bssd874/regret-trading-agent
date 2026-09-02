from pydantic import BaseModel
from openai import OpenAI

from backend.app.core.config import settings


class AzureProvider:
    """Azure structured-output provider for analysis-only agents."""

    def __init__(self):
        endpoint = settings.azure_openai_endpoint.rstrip("/") + "/"

        self.client = OpenAI(
            api_key=settings.azure_openai_api_key,
            base_url=endpoint,
            timeout=settings.azure_openai_timeout_seconds,
            max_retries=1,
        )

    def generate(
        self,
        prompt: str,
        *,
        response_model: type[BaseModel],
    ) -> str:
        response = self.client.responses.parse(
            model=settings.azure_openai_deployment,
            input=prompt,
            text_format=response_model,
            timeout=settings.azure_openai_timeout_seconds,
        )

        text = response.output_text

        if not text:
            raise RuntimeError("Azure returned empty structured output")

        if response.output_parsed is None:
            raise RuntimeError("Azure did not return schema-valid output")

        return text


azure_provider = AzureProvider()
