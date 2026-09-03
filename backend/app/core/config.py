from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    app_name: str = "REGRET API"

    # =========================================================
    # Alpaca — PAPER ONLY
    # =========================================================
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool = True

    # =========================================================
    # Azure OpenAI — Primary Analyst
    # =========================================================
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
    )

    # =========================================================
    # NVIDIA NIM — Kimi K3 Adversarial Critic
    # =========================================================
    nvidia_api_key: str

    nvidia_base_url: str = (
        "https://integrate.api.nvidia.com/v1"
    )

    nvidia_model: str = "moonshotai/kimi-k3"

    # Bound the hosted critic's latency for an interactive demo.
    nvidia_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
    )

    # Keep reasoning lower than max to reduce latency.
    nvidia_reasoning_effort: Literal["low", "medium", "high", "max"] = "low"

    # Enough for structured critic JSON.
    nvidia_max_tokens: int = Field(
        default=512,
        ge=1,
        le=4096,
    )

    # =========================================================
    # Execution Safety
    # =========================================================
    paper_execution_enabled: bool = False

    # 0.02 = 2% of paper account equity
    execution_position_pct: float = Field(
        default=0.02,
        gt=0,
        le=0.05,
    )

    # =========================================================
    # Autonomous orchestration
    # =========================================================
    autonomous_agent_enabled: bool = False

    autonomous_cycle_seconds: int = Field(
        default=300,
        gt=0,
    )

    autonomous_max_candidates_per_cycle: int = Field(
        default=2,
        ge=1,
        le=10,
    )

    autonomous_stale_cycle_seconds: int = Field(
        default=900,
        gt=0,
    )

    # =========================================================
    # Database
    # =========================================================
    database_url: str = "sqlite:///./regret.db"

    # =========================================================
    # Environment
    # =========================================================
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================
    # Safety validators
    # =========================================================
    @field_validator("alpaca_paper")
    @classmethod
    def enforce_paper_only(
        cls,
        value: bool,
    ) -> bool:
        if value is not True:
            raise ValueError(
                "REGRET is PAPER ONLY. "
                "ALPACA_PAPER must remain true."
            )

        return value

    @field_validator("nvidia_reasoning_effort", mode="before")
    @classmethod
    def validate_nvidia_reasoning_effort(
        cls,
        value: object,
    ) -> str:
        normalized = str(value).strip().lower()
        return normalized

    @model_validator(mode="after")
    def validate_autonomous_cycle_window(self):
        if self.autonomous_stale_cycle_seconds <= self.autonomous_cycle_seconds:
            raise ValueError(
                "AUTONOMOUS_STALE_CYCLE_SECONDS must be greater than "
                "AUTONOMOUS_CYCLE_SECONDS"
            )

        return self


settings = Settings()
