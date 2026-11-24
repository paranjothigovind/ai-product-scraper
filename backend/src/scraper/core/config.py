from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated once at startup; a bad environment fails before any work starts."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Which LLM backs extraction. MODEL_* names are model ids for "anthropic" and Azure
    # deployment names for "azure".
    llm_provider: Literal["anthropic", "azure"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    azure_openai_endpoint: HttpUrl | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "2024-10-21"
    model_extract: str = Field(min_length=1)
    model_judge: str = Field(min_length=1)
    model_escalate: str = Field(min_length=1)

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint: HttpUrl
    s3_region: str = "us-east-1"
    s3_bucket: str = Field(min_length=1)
    s3_access_key_id: str = Field(min_length=1)
    s3_secret_access_key: SecretStr

    # Identifies us to site operators; set a real contact URL in production.
    user_agent: str = "AIProductScraperBot/0.1 (+https://example.com/bot)"
    egress_proxy_url: HttpUrl | None = None

    max_pages_total: int = Field(default=50, ge=1)
    max_retries: int = Field(default=2, ge=0)
    # TODO(next): spec gave no default; placeholder until the extractor phase measures real usage.
    max_tokens_per_run: int = Field(default=200_000, ge=1)
    min_quality: float = Field(default=0.75, ge=0, le=1)
    plan_cap_products: int = Field(default=500, ge=1)

    @model_validator(mode="after")
    def _provider_credentials(self) -> Self:
        if self.llm_provider == "anthropic":
            missing = [] if self.anthropic_api_key else ["anthropic_api_key"]
        else:
            missing = [
                name
                for name in ("azure_openai_endpoint", "azure_openai_api_key")
                if getattr(self, name) is None
            ]
        if missing:
            raise ValueError(f"required for llm_provider={self.llm_provider}: {', '.join(missing)}")
        return self


class ConfigError(RuntimeError):
    pass


def load_settings(**kwargs: Any) -> Settings:
    """Builds Settings, reporting field names and reasons only: pydantic's own error text
    echoes input values, which can include a database password."""
    try:
        return Settings(**kwargs)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"Invalid environment: {problems}") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
