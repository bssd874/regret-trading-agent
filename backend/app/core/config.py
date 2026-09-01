from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "REGRET API"

    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool = True

    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    nvidia_api_key: str
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "moonshotai/kimi-k3"
    nvidia_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    nvidia_max_tokens: int = Field(default=4096, ge=1, le=65536)
    nvidia_reasoning_effort: Literal["low", "high", "max"] = "low"

    database_url: str = "sqlite:///./regret.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("alpaca_paper")
    @classmethod
    def require_paper_trading(cls, value: bool) -> bool:
        if not value:
            raise ValueError("REGRET supports Alpaca paper trading only")

        return value


settings = Settings()
