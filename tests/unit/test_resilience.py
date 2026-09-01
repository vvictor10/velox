from __future__ import annotations

from datetime import UTC, datetime

from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.providers.resilience import RetryPolicy, build_fallback_record, execute_with_retry


def test_execute_with_retry_preserves_failed_attempt_and_retried_success() -> None:
    calls = {"count": 0}

    def flaky_tool() -> ToolResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return ToolResult.failure(
                tool_name="finnhub.company_news",
                source="Finnhub /company-news",
                started_at=datetime.now(UTC),
                error="Temporary timeout.",
                failure_category=FailureCategory.RECOVERABLE,
            )
        return ToolResult.success(
            tool_name="finnhub.company_news",
            source="Finnhub /company-news",
            started_at=datetime.now(UTC),
            data=[],
        )

    outcome = execute_with_retry(
        flaky_tool,
        policy=RetryPolicy(max_retries=1),
        retry_message="Retrying news fetch.",
    )

    assert calls["count"] == 2
    assert [result.status for result in outcome.results] == [
        ToolStatus.FAILED,
        ToolStatus.RETRIED,
    ]
    assert outcome.retry_records[0].user_message == "Retrying news fetch."


def test_execute_with_retry_does_not_retry_degraded_continuable_failure() -> None:
    calls = {"count": 0}

    def empty_news() -> ToolResult:
        calls["count"] += 1
        return ToolResult.failure(
            tool_name="alpha_vantage.news_sentiment",
            source="Alpha Vantage NEWS_SENTIMENT",
            started_at=datetime.now(UTC),
            status=ToolStatus.SKIPPED,
            error="Live calls are disabled.",
            failure_category=FailureCategory.DEGRADED_CONTINUABLE,
        )

    outcome = execute_with_retry(empty_news, policy=RetryPolicy(max_retries=1))

    assert calls["count"] == 1
    assert outcome.retry_records == []
    assert outcome.final_result.status == ToolStatus.SKIPPED


def test_build_fallback_record_requires_visible_primary_gap_and_successful_fallback() -> None:
    primary = ToolResult.failure(
        tool_name="alpha_vantage.news_sentiment",
        source="Alpha Vantage NEWS_SENTIMENT",
        started_at=datetime.now(UTC),
        status=ToolStatus.SKIPPED,
        error="Alpha disabled.",
        failure_category=FailureCategory.DEGRADED_CONTINUABLE,
    )
    fallback = ToolResult.success(
        tool_name="finnhub.company_news",
        source="Finnhub /company-news",
        started_at=datetime.now(UTC),
        data=[],
    )

    record = build_fallback_record(
        primary=primary,
        fallback=fallback,
        user_message="Using Finnhub company news.",
    )

    assert record is not None
    assert record.primary_tool_name == "alpha_vantage.news_sentiment"
    assert record.fallback_tool_name == "finnhub.company_news"
    assert record.reason == "Alpha disabled."


def test_build_fallback_record_does_not_mark_fallback_without_primary_gap() -> None:
    primary = ToolResult.success(
        tool_name="alpha_vantage.news_sentiment",
        source="Alpha Vantage NEWS_SENTIMENT",
        started_at=datetime.now(UTC),
        data={},
    )
    fallback = ToolResult.success(
        tool_name="finnhub.company_news",
        source="Finnhub /company-news",
        started_at=datetime.now(UTC),
        data=[],
    )

    assert (
        build_fallback_record(
            primary=primary,
            fallback=fallback,
            user_message="Using Finnhub company news.",
        )
        is None
    )
