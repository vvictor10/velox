"""OpenAI-compatible LLM access for Nebius and Fireworks."""

from __future__ import annotations

import json
from enum import StrEnum
from time import perf_counter
from typing import Any, TypeVar

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ValidationError

from velox.config import AppSettings
from velox.models.telemetry import FailureCategory, TelemetrySpan
from velox.observability import traceable_step

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LlmProvider(StrEnum):
    NEBIUS = "nebius"
    FIREWORKS = "fireworks"


class LlmCallResult(BaseModel):
    provider: LlmProvider
    model_id: str
    prompt_name: str
    prompt_version: str
    output: dict[str, Any] | None = None
    raw_text: str | None = None
    schema_valid: bool = False
    error: str | None = None
    telemetry: TelemetrySpan


class ModelInfo(BaseModel):
    provider: LlmProvider
    model_id: str
    owned_by: str | None = None


class VeloxLlmClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def list_models(self, provider: LlmProvider) -> list[ModelInfo]:
        client = self._client(provider)
        models = client.models.list()
        return [
            ModelInfo(
                provider=provider,
                model_id=model.id,
                owned_by=getattr(model, "owned_by", None),
            )
            for model in models.data
        ]

    def call_structured(
        self,
        *,
        provider: LlmProvider,
        model_id: str,
        prompt_name: str,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: type[SchemaT],
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> LlmCallResult:
        metadata = {
            "provider": provider.value,
            "model_id": model_id,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
        }

        def invoke() -> LlmCallResult:
            return self._call_structured_untraced(
                provider=provider,
                model_id=model_id,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                system_prompt=system_prompt,
                user_payload=user_payload,
                output_schema=output_schema,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return traceable_step(
            name=f"llm.{prompt_name}",
            run_type="llm",
            metadata=metadata,
            settings=self.settings,
        )(invoke)()

    def _call_structured_untraced(
        self,
        *,
        provider: LlmProvider,
        model_id: str,
        prompt_name: str,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: type[SchemaT],
        temperature: float,
        max_tokens: int,
    ) -> LlmCallResult:
        started = perf_counter()
        span = TelemetrySpan(
            name=f"llm.{prompt_name}",
            kind="llm",
            provider=provider.value,
            model_id=model_id,
            prompt_version=prompt_version,
        )
        try:
            response = self._client(provider).chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, default=str)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_schema.__name__,
                        "schema": output_schema.model_json_schema(),
                    },
                },
            )
            raw_text = _content_from_response(response)
            parsed_json = json.loads(raw_text)
            parsed = output_schema.model_validate(parsed_json)
            telemetry = _finish_span(span, started, response)
            return LlmCallResult(
                provider=provider,
                model_id=model_id,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                output=parsed.model_dump(),
                raw_text=raw_text,
                schema_valid=True,
                telemetry=telemetry,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            telemetry = _finish_span(
                span.model_copy(update={"failure_category": FailureCategory.RECOVERABLE}),
                started,
                None,
            )
            return LlmCallResult(
                provider=provider,
                model_id=model_id,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                raw_text=locals().get("raw_text"),
                schema_valid=False,
                error=f"LLM structured output validation failed: {exc}",
                telemetry=telemetry,
            )
        except (APIConnectionError, APIError, APITimeoutError, RateLimitError, RuntimeError, ValueError) as exc:
            telemetry = _finish_span(
                span.model_copy(update={"failure_category": FailureCategory.NON_RECOVERABLE}),
                started,
                None,
            )
            return LlmCallResult(
                provider=provider,
                model_id=model_id,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                schema_valid=False,
                error=str(exc),
                telemetry=telemetry,
            )

    def _client(self, provider: LlmProvider) -> OpenAI:
        if provider == LlmProvider.NEBIUS:
            if self.settings.nebius_api_key is None:
                raise ValueError("NEBIUS_API_KEY is not configured.")
            return OpenAI(
                api_key=self.settings.nebius_api_key.get_secret_value(),
                base_url=self.settings.nebius_base_url,
            )
        if self.settings.fireworks_api_key is None:
            raise ValueError("FIREWORKS_API_KEY is not configured.")
        return OpenAI(
            api_key=self.settings.fireworks_api_key.get_secret_value(),
            base_url=self.settings.fireworks_base_url,
        )


def _content_from_response(response: ChatCompletion) -> str:
    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM response content was empty.")
    return content


def _finish_span(
    span: TelemetrySpan,
    started: float,
    response: ChatCompletion | None,
) -> TelemetrySpan:
    usage = getattr(response, "usage", None) if response is not None else None
    elapsed_ms = int((perf_counter() - started) * 1000)
    return span.finish().model_copy(
        update={
            "duration_ms": elapsed_ms,
            "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        }
    )
