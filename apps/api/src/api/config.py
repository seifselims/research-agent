"""Typed application settings, loaded from environment variables and apps/api/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/.env, found relative to this file so it works from any working directory.
# On Render there is no .env file; values come from the service's environment instead.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

SUPPORTED_PROVIDERS = ("gemini", "groq")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str

    gemini_api_key: SecretStr
    groq_api_key: SecretStr

    llm_main_model: str
    llm_fast_model: str
    embedding_model: str
    embedding_dimensions: int = 768

    cors_origins: str = "http://localhost:3001"

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator("database_url")
    @classmethod
    def use_asyncpg_driver(cls, url: str) -> str:
        """Render gives postgres:// URLs; SQLAlchemy needs postgresql+asyncpg://."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url.removeprefix(prefix)
        return url

    @field_validator("llm_main_model", "llm_fast_model", "embedding_model")
    @classmethod
    def check_model_format(cls, model: str) -> str:
        provider, _, name = model.partition("/")
        if provider not in SUPPORTED_PROVIDERS or not name:
            raise ValueError(
                f"expected 'provider/model-id' with provider in {SUPPORTED_PROVIDERS}, "
                f"got {model!r}"
            )
        return model

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def api_key_for(self, model: str) -> str:
        """Return the API key for a LiteLLM model string like 'groq/openai/gpt-oss-120b'."""
        provider = model.partition("/")[0]
        keys = {"gemini": self.gemini_api_key, "groq": self.groq_api_key}
        return keys[provider].get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
