from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "REGRET API"

    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool = True

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
