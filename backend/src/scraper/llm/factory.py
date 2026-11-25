import anthropic
import openai

from scraper.core.config import Settings
from scraper.llm.azure import AzureOpenAIExtractor
from scraper.llm.extractor import AnthropicExtractor, LLMExtractor


def build_extractor(settings: Settings) -> LLMExtractor:
    """The extractor for `settings.llm_provider`, using MODEL_EXTRACT as its model."""
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
        return AzureOpenAIExtractor(client, settings.model_extract)
    assert settings.anthropic_api_key  # noqa: S101  # validated by Settings
    return AnthropicExtractor(
        anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value()),
        settings.model_extract,
    )
