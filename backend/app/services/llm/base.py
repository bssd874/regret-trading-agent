from typing import Protocol

from pydantic import BaseModel


class StructuredLLMProvider(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        response_model: type[BaseModel],
    ) -> str:
        """Return JSON constrained to response_model's schema."""

        ...
