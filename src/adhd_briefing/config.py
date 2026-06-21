"""Konfiguracja aplikacji ładowana z .env przez pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    anthropic_api_key: str = ""
    db_path: str = "adhd.db"
    default_timezone: str = "Europe/Warsaw"
    briefing_max_articles: int = 5
    summarizer_model: str = "claude-haiku-4-5-20251001"
    llm_concurrency: int = 3


settings = Settings()
