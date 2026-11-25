import anthropic
import openai

from scraper.core.config import Settings
from scraper.llm.azure import AzureOpenAIExtractor
from scraper.llm.extractor import AnthropicExtractor, LLMExtractor


def build_extractor(settings: Settings, model: str | None = None) -> LLMExtractor:
    """The extractor for `settings.llm_provider`; `model` defaults to MODEL_EXTRACT (pass
    `settings.model_escalate` for the stronger retry model)."""
    model = model or settings.model_extract
    if settings.llm_provider == "azure":
        assert settings.azure_openai_endpoint and settings.azure_openai_api_key  # noqa: S101  # validated by Settings
        endpoint = str(settings.azure_openai_endpoint).rstrip("/")
        key = settings.azure_openai_api_key.get_secret_value()
        client: openai.AsyncOpenAI
        if endpoint.endswith("/openai/v1"):
            # Azure's v1 API: plain OpenAI client, no api-version.
            client = openai.AsyncOpenAI(base_url=endpoint + "/", api_key=key)
        else:
            client = openai.AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=key,
                api_version=settings.azure_openai_api_version,
            )
        return AzureOpenAIExtractor(client, model)
    assert settings.anthropic_api_key  # noqa: S101  # validated by Settings
    return AnthropicExtractor(
        anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value()),
        model,
    )
