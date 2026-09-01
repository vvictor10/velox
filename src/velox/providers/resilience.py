"""Retry and fallback helpers for provider calls."""

from __future__ import annotations

from collections.abc import Callable
from time import sleep

from pydantic import BaseModel, Field

from velox.models.failures import FallbackRecord, RetryRecord
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus


class RetryPolicy(BaseModel):
    max_retries: int = 1
    retry_delay_seconds: float = 0


class RetryOutcome(BaseModel):
    results: list[ToolResult] = Field(default_factory=list)
    retry_records: list[RetryRecord] = Field(default_factory=list)

    @property
    def final_result(self) -> ToolResult:
        return self.results[-1]


def execute_with_retry(
    call: Callable[[], ToolResult],
    *,
    policy: RetryPolicy | None = None,
    retry_message: str | None = None,
) -> RetryOutcome:
    """Execute a provider call and retry recoverable failures visibly."""

    resolved_policy = policy or RetryPolicy()
    results: list[ToolResult] = []
    retry_records: list[RetryRecord] = []

    for attempt_index in range(resolved_policy.max_retries + 1):
        result = call()
        if attempt_index > 0 and result.status == ToolStatus.SUCCESS:
            result = result.model_copy(update={"status": ToolStatus.RETRIED})
        results.append(result)

        should_retry = (
            result.failure_category == FailureCategory.RECOVERABLE
            and result.status == ToolStatus.FAILED
            and attempt_index < resolved_policy.max_retries
        )
        if not should_retry:
            break

        retry_records.append(
            RetryRecord(
                tool_name=result.tool_name,
                attempt_count=attempt_index + 1,
                reason=result.error or "Recoverable tool failure.",
                failure_category=result.failure_category,
                user_message=retry_message or f"Retrying {result.tool_name} after a recoverable error.",
            )
        )
        if resolved_policy.retry_delay_seconds > 0:
            sleep(resolved_policy.retry_delay_seconds)

    return RetryOutcome(results=results, retry_records=retry_records)


def build_fallback_record(
    *,
    primary: ToolResult,
    fallback: ToolResult,
    user_message: str,
) -> FallbackRecord | None:
    """Create a fallback record when a successful fallback follows a visible primary gap."""

    primary_failed_or_skipped = primary.status in {
        ToolStatus.FAILED,
        ToolStatus.SKIPPED,
        ToolStatus.LOOKUP_FAILED,
    }
    fallback_succeeded = fallback.status in {
        ToolStatus.SUCCESS,
        ToolStatus.RETRIED,
        ToolStatus.FALLBACK_USED,
    }
    if not primary_failed_or_skipped or not fallback_succeeded:
        return None
    return FallbackRecord(
        primary_tool_name=primary.tool_name,
        fallback_tool_name=fallback.tool_name,
        reason=primary.error or f"{primary.tool_name} was unavailable.",
        user_message=user_message,
    )
