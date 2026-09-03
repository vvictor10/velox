"""Composed public-data collection for one selected company."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from velox.config import AppSettings
from velox.models.company import CompanyIdentity
from velox.models.earnings import EarningsSnapshot
from velox.models.evidence import EvidencePack
from velox.models.failures import FallbackRecord, RetryRecord
from velox.models.news import NewsSnapshot
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.models.warnings import WarningRecord
from velox.observability import traceable_step
from velox.providers.alpha_vantage import AlphaVantageClient
from velox.providers.finnhub import FinnhubClient
from velox.providers.normalization import (
    build_evidence_pack,
    normalize_earnings_snapshot,
    normalize_news_snapshot,
)
from velox.providers.resilience import RetryPolicy, build_fallback_record, execute_with_retry
from velox.providers.sec import SecClient


class PublicDataBundle(BaseModel):
    company: CompanyIdentity
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence_pack: EvidencePack
    earnings: EarningsSnapshot
    news: NewsSnapshot
    warnings: list[WarningRecord] = Field(default_factory=list)
    retry_records: list[RetryRecord] = Field(default_factory=list)
    fallback_records: list[FallbackRecord] = Field(default_factory=list)

    @property
    def has_minimum_evidence(self) -> bool:
        has_identity = self.company.cik is not None
        has_earnings = self.earnings.has_forward_calendar or self.earnings.has_historical_earnings
        has_context = any(
            result.status == ToolStatus.SUCCESS and result.tool_name.startswith("sec.")
            for result in self.tool_results
        )
        return bool(has_identity and has_earnings and has_context)

    @property
    def completed_with_warnings(self) -> bool:
        return bool(self.warnings or self.evidence_pack.warnings)


def collect_public_data(company: CompanyIdentity, settings: AppSettings) -> PublicDataBundle:
    """Collect public evidence using provider controls from settings.

    Alpha Vantage calls are visible skips unless explicitly enabled, which lets
    development continue on SEC/Finnhub without exhausting Alpha's daily budget.
    """

    alpha_vantage = AlphaVantageClient(settings)
    finnhub = FinnhubClient(settings)
    sec = SecClient(settings)

    retry_policy = RetryPolicy(max_retries=1)
    outcomes = [
        execute_with_retry(
            _traced_tool_call(
                settings,
                "alpha_vantage.earnings_calendar",
                lambda: alpha_vantage.earnings_calendar(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Alpha Vantage earnings calendar.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "alpha_vantage.earnings_history",
                lambda: alpha_vantage.earnings_history(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Alpha Vantage earnings history.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "alpha_vantage.earnings_estimates",
                lambda: alpha_vantage.earnings_estimates(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Alpha Vantage earnings estimates.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "alpha_vantage.news_sentiment",
                lambda: _alpha_news_sentiment(company, settings, alpha_vantage),
            ),
            policy=retry_policy,
            retry_message="Retrying Alpha Vantage news fetch.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "alpha_vantage.company_overview",
                lambda: alpha_vantage.company_overview(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Alpha Vantage company overview.",
        ),
        execute_with_retry(
            _traced_tool_call(settings, "sec.submissions", lambda: sec.submissions(company)),
            policy=retry_policy,
            retry_message="Retrying SEC submissions fetch.",
        ),
        execute_with_retry(
            _traced_tool_call(settings, "sec.company_facts", lambda: sec.company_facts(company)),
            policy=retry_policy,
            retry_message="Retrying SEC company facts fetch.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "finnhub.earnings_calendar",
                lambda: finnhub.earnings_calendar(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Finnhub earnings calendar.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "finnhub.earnings_surprises",
                lambda: finnhub.earnings_surprises(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Finnhub earnings surprises.",
        ),
        execute_with_retry(
            _traced_tool_call(
                settings,
                "finnhub.company_news",
                lambda: finnhub.company_news(company.ticker),
            ),
            policy=retry_policy,
            retry_message="Retrying Finnhub company news.",
        ),
    ]
    tool_results = [result for outcome in outcomes for result in outcome.results]
    retry_records = [record for outcome in outcomes for record in outcome.retry_records]
    fallback_records = _fallback_records(tool_results)
    evidence_pack = build_evidence_pack(tool_results)
    earnings = normalize_earnings_snapshot(company.ticker, evidence_pack)
    news = normalize_news_snapshot(company.ticker, evidence_pack, company_name=company.company_name)
    warnings = [*evidence_pack.warnings, *earnings.warnings, *news.warnings]

    return PublicDataBundle(
        company=company,
        tool_results=tool_results,
        evidence_pack=evidence_pack,
        earnings=earnings,
        news=news,
        warnings=warnings,
        retry_records=retry_records,
        fallback_records=fallback_records,
    )


def _traced_tool_call(settings: AppSettings, tool_name: str, call):
    return traceable_step(
        name=tool_name,
        run_type="tool",
        metadata={"tool_name": tool_name},
        settings=settings,
    )(call)


def _alpha_news_sentiment(
    company: CompanyIdentity,
    settings: AppSettings,
    alpha_vantage: AlphaVantageClient,
) -> ToolResult:
    if not settings.velox_demo_force_alpha_news_failure:
        return alpha_vantage.news_sentiment(company.ticker)
    return ToolResult.failure(
        tool_name="alpha_vantage.news_sentiment",
        source="Alpha Vantage NEWS_SENTIMENT",
        started_at=datetime.now(UTC),
        error="Alpha Vantage news was unavailable.",
        failure_category=FailureCategory.RECOVERABLE,
    )


def _fallback_records(tool_results: list[ToolResult]) -> list[FallbackRecord]:
    by_name = {result.tool_name: result for result in tool_results}
    candidates = [
        (
            "alpha_vantage.earnings_calendar",
            "finnhub.earnings_calendar",
            "Alpha Vantage earnings calendar was unavailable; using Finnhub calendar evidence.",
        ),
        (
            "alpha_vantage.earnings",
            "finnhub.earnings_surprises",
            "Alpha Vantage earnings history was unavailable; using Finnhub recent surprises.",
        ),
        (
            "alpha_vantage.news_sentiment",
            "finnhub.company_news",
            "Alpha Vantage news was unavailable; using Finnhub company news.",
        ),
    ]
    records: list[FallbackRecord] = []
    for primary_name, fallback_name, message in candidates:
        primary = by_name.get(primary_name)
        fallback = by_name.get(fallback_name)
        if primary is None or fallback is None:
            continue
        record = build_fallback_record(primary=primary, fallback=fallback, user_message=message)
        if record is not None:
            records.append(record)
    return records
