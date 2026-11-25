"""Extractor for Azure OpenAI / Azure AI Foundry deployments (for example gpt-4o-mini)."""

import openai

from scraper.core.errors import ScrapeError
from scraper.llm.extractor import (
    SYSTEM_PROMPT,
    ExtractedPage,
    ExtractionResult,
    build_user_prompt,
)
from scraper.schemas.error_code import ErrorCode


class AzureOpenAIExtractor:
    """`model` is the Azure *deployment name*, which is whatever you called the deployment."""

    def __init__(
        self, client: openai.AsyncOpenAI, model: str, *, max_output_tokens: int = 8000
    ) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def extract(
        self, text: str, *, page_url: str | None, feedback: str = ""
    ) -> ExtractionResult:
        try:
            response = await self._client.chat.completions.parse(
                model=self._model,
                max_completion_tokens=self._max_output_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(text, page_url, feedback)},
                ],
                response_format=ExtractedPage,
            )
        except openai.OpenAIError as exc:
            raise ScrapeError(ErrorCode.LLM_FAILED, f"LLM call failed: {exc}") from exc
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        choice = response.choices[0]
        parsed = choice.message.parsed
        if choice.finish_reason in ("length", "content_filter") or parsed is None:
            return ExtractionResult(products=[], tokens_in=tokens_in, tokens_out=tokens_out)
        return ExtractionResult(
            products=parsed.products, tokens_in=tokens_in, tokens_out=tokens_out
        )
