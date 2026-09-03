import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
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

    # Public deployments must not let anonymous visitors start expensive
    # autonomous cycles. This gate is independent from execution safety.
    public_agent_trigger_enabled: bool = False

    # 0.02 = 2% of paper account equity
    execution_position_pct: float = Field(
        default=0.02,
        gt=0,
        le=0.05,
    )

    # =========================================================
    # Deterministic Market Scout quality gate
    # =========================================================
    market_scout_min_price: float = Field(
        default=5.0,
        gt=0,
        le=1000,
    )

    market_scout_min_previous_daily_volume: int = Field(
        default=500_000,
        ge=1,
        le=100_000_000,
    )

    market_scout_max_daily_change_pct: float = Field(
        default=25.0,
        gt=0,
        le=100,
    )

    # =========================================================
    # Autonomous orchestration
    # =========================================================
    autonomous_agent_enabled: bool = False

    # Existing paper positions may still be reconciled and exited while
    # discovery of new autonomous entries remains independently disabled.
    autonomous_new_entries_enabled: bool = False

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

    # Browser access is read-only. Production adds the deployed frontend
    # origin explicitly; wildcard origins are rejected.
    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

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

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("DATABASE_URL must not be empty")
        if normalized.startswith("postgres://"):
            return (
                "postgresql+psycopg://"
                + normalized[len("postgres://"):]
            )
        if normalized.startswith("postgresql://"):
            return (
                "postgresql+psycopg://"
                + normalized[len("postgresql://"):]
            )
        return normalized

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError("CORS_ALLOWED_ORIGINS is invalid JSON") from exc
            else:
                value = raw.split(",") if raw else []

        if not isinstance(value, (list, tuple)):
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must be a list "
                "or comma-separated string"
            )

        origins: list[str] = []
        for item in value:
            origin = str(item).strip().rstrip("/")
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS entries must be explicit HTTP(S) origins"
                )
            if origin not in origins:
                origins.append(origin)

        if not origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin")
        return origins

    @model_validator(mode="after")
    def validate_autonomous_cycle_window(self):
        if self.autonomous_stale_cycle_seconds <= self.autonomous_cycle_seconds:
            raise ValueError(
                "AUTONOMOUS_STALE_CYCLE_SECONDS must be greater than "
                "AUTONOMOUS_CYCLE_SECONDS"
            )

        return self


settings = Settings()
