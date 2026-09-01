from __future__ import annotations

from datetime import UTC, datetime

from velox.models.company import CompanyIdentity
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.providers.normalization import (
    build_evidence_pack,
    normalize_earnings_snapshot,
    normalize_news_snapshot,
)
from velox.providers.research_data import PublicDataBundle


def test_public_data_bundle_minimum_evidence_with_finnhub_and_sec() -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    started_at = datetime.now(UTC)
    tool_results = [
        ToolResult.failure(
            tool_name="alpha_vantage.earnings_calendar",
            source="Alpha Vantage EARNINGS_CALENDAR",
            started_at=started_at,
            status=ToolStatus.SKIPPED,
            failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            error="Alpha disabled.",
        ),
        ToolResult.success(
            tool_name="sec.submissions",
            source="SEC EDGAR submissions",
            started_at=started_at,
            data={"cik": "320193", "name": "Apple Inc."},
        ),
        ToolResult.success(
            tool_name="finnhub.earnings_calendar",
            source="Finnhub /calendar/earnings",
            started_at=started_at,
            data={"earningsCalendar": [{"date": "2026-10-29", "symbol": "AAPL"}]},
        ),
    ]
    evidence_pack = build_evidence_pack(tool_results)
    bundle = PublicDataBundle(
        company=company,
        tool_results=tool_results,
        evidence_pack=evidence_pack,
        earnings=normalize_earnings_snapshot("AAPL", evidence_pack),
        news=normalize_news_snapshot("AAPL", evidence_pack),
        warnings=evidence_pack.warnings,
    )

    assert bundle.has_minimum_evidence is True
    assert bundle.completed_with_warnings is True


def test_public_data_bundle_carries_retry_and_fallback_records() -> None:
    from velox.models.failures import FallbackRecord, RetryRecord

    bundle = PublicDataBundle(
        company=CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", cik="320193"),
        tool_results=[],
        evidence_pack=build_evidence_pack([]),
        earnings=normalize_earnings_snapshot("AAPL", build_evidence_pack([])),
        news=normalize_news_snapshot("AAPL", build_evidence_pack([])),
        retry_records=[
            RetryRecord(
                tool_name="finnhub.company_news",
                attempt_count=1,
                reason="Timeout",
                failure_category=FailureCategory.RECOVERABLE,
                user_message="Retrying news fetch.",
            )
        ],
        fallback_records=[
            FallbackRecord(
                primary_tool_name="alpha_vantage.news_sentiment",
                fallback_tool_name="finnhub.company_news",
                reason="Alpha disabled.",
                user_message="Using Finnhub company news.",
            )
        ],
    )

    assert bundle.retry_records[0].user_message == "Retrying news fetch."
    assert bundle.fallback_records[0].fallback_tool_name == "finnhub.company_news"
