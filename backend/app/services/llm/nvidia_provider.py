from pydantic import BaseModel
from openai import OpenAI

from backend.app.core.config import settings


class NvidiaProvider:
    """NVIDIA NIM provider used only by the adversarial critic."""

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url.rstrip("/"),
            timeout=settings.nvidia_timeout_seconds,
            # A critic timeout must become CRITIC_FAILED promptly; an
            # implicit retry can otherwise double the failure window.
            max_retries=0,
        )

    def generate(
        self,
        prompt: str,
        *,
        response_model: type[BaseModel],
    ) -> str:
        schema = response_model.model_json_schema()
        response = self.client.chat.completions.create(
            model=settings.nvidia_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": True,
                    "schema": schema,
                },
            },
            # Kimi K3 defaults to max reasoning effort. Low is sufficient
            # for this bounded single-step critique and avoids long stalls.
            reasoning_effort=settings.nvidia_reasoning_effort,
            temperature=1.0,
            max_tokens=settings.nvidia_max_tokens,
            timeout=settings.nvidia_timeout_seconds,
        )

        text = response.choices[0].message.content

        if not text:
            raise RuntimeError("NVIDIA Kimi returned empty structured output")

        return text


nvidia_provider = NvidiaProvider()
