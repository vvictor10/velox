from __future__ import annotations

from datetime import UTC, date, datetime

from velox.models.company import CompanyIdentity
from velox.models.earnings import EarningsEvent, EarningsSnapshot, HistoricalEarningsQuarter
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.news import NewsItem, NewsSnapshot
from velox.models.report import (
    ApprovalStatus,
    DeltaCategory,
    DeltaFinding,
    EarningsBrief,
    PriorReportMemory,
    PriorReportStatus,
    ReportSection,
    ReviewerFinding,
    ReviewerResult,
    RiskFinding,
)
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.models.warnings import WarningRecord


def test_evidence_pack_assigns_ids_and_builds_source_table() -> None:
    pack = EvidencePack(
        records=[
            EvidenceRecord(
                evidence_type=EvidenceType.EARNINGS,
                provider="Finnhub",
                title="Earnings calendar",
                source_url="https://example.test/earnings",
            ),
            EvidenceRecord(
                evidence_type=EvidenceType.NEWS,
                provider="Alpha Vantage",
                title="Recent news",
                source_url="https://example.test/news",
            ),
        ]
    ).assign_ids()

    assert [record.evidence_id for record in pack.records] == ["E1", "E2"]
    assert pack.validate_citations(["E1", "E99"]) == ["E99"]
    assert pack.source_table()[0].evidence_id == "E1"


def test_run_state_adds_warning_for_failed_tool_result() -> None:
    started_at = datetime.now(UTC)
    result = ToolResult.failure(
        tool_name="alpha_vantage.news_sentiment",
        source="Alpha Vantage NEWS_SENTIMENT",
        started_at=started_at,
        status=ToolStatus.SKIPPED,
        failure_category=FailureCategory.DEGRADED_CONTINUABLE,
        error="Alpha Vantage live calls are disabled.",
    )

    state = RunState(selected_ticker="AAPL").add_tool_result(result)

    assert len(state.tool_results) == 1
    assert len(state.warnings) == 1
    assert state.warnings[0].failure_category == FailureCategory.DEGRADED_CONTINUABLE
    assert state.completed_with_warnings() is True


def test_happy_path_state_can_hold_core_artifacts() -> None:
    company = CompanyIdentity(
        ticker="AAPL",
        company_name="Apple Inc.",
        exchange="Nasdaq",
        cik="320193",
    )
    earnings = EarningsSnapshot(
        ticker="AAPL",
        next_event=EarningsEvent(
            report_date=date(2026, 10, 29),
            fiscal_quarter=4,
            fiscal_year=2026,
            eps_estimate=1.5,
            revenue_estimate=100_000_000_000,
            source_provider="Finnhub",
            source_evidence_id="E1",
        ),
        history=[
            HistoricalEarningsQuarter(
                period=date(2026, 6, 30),
                fiscal_quarter=3,
                fiscal_year=2026,
                eps_actual=1.4,
                eps_estimate=1.35,
                surprise=0.05,
                source_provider="Finnhub",
                source_evidence_id="E2",
            )
        ],
    )
    news = NewsSnapshot(
        ticker="AAPL",
        items=[
            NewsItem(
                headline="Apple reports services growth",
                source="Example News",
                published_at=datetime.now(UTC),
                source_provider="Finnhub",
                source_evidence_id="E3",
            )
        ],
    )
    brief = EarningsBrief(
        ticker="AAPL",
        company_name="Apple Inc.",
        sections=[
            ReportSection(
                title="Earnings Setup",
                body="Next earnings are expected after market close.",
                citation_ids=["E1"],
            )
        ],
    )
    reviewer = ReviewerResult(
        passed=True,
        findings=[
            ReviewerFinding(
                code="citations.valid",
                message="Citations resolve to evidence records.",
                severity="info",
            )
        ],
    )

    state = RunState(
        selected_ticker="AAPL",
        company=company,
        status=RunStatus.WAITING_FOR_APPROVAL,
        earnings=earnings,
        news=news,
        evidence_pack=EvidencePack(
            records=[
                EvidenceRecord(
                    evidence_id="E1",
                    evidence_type=EvidenceType.EARNINGS,
                    provider="Finnhub",
                    title="Earnings calendar",
                )
            ]
        ),
        prior_memory=PriorReportMemory(ticker="AAPL", cik="320193", status=PriorReportStatus.MISSING),
        delta_findings=[
            DeltaFinding(category=DeltaCategory.MISSING_PRIOR, finding="No prior report was found.")
        ],
        risk_findings=[
            RiskFinding(
                risk="Margin pressure",
                severity="medium",
                rationale="Recent quarter showed cost pressure.",
                supporting_evidence_ids=["E2"],
            )
        ],
        brief=brief,
        reviewer_result=reviewer,
        approval_status=ApprovalStatus.AWAITING_APPROVAL,
        warnings=[WarningRecord(code="news.partial", message="News feed was capped.")],
    )

    assert state.company.cik_padded == "0000320193"
    assert state.earnings and state.earnings.has_forward_calendar
    assert state.news and state.news.has_recent_news
    assert state.brief and state.brief.all_citation_ids() == ["E1"]
    assert state.reviewer_result and state.reviewer_result.passed is True
    assert state.completed_with_warnings() is True


def test_company_identity_has_friendly_display_name() -> None:
    assert (
        CompanyIdentity(
            ticker="AMZN",
            company_name="AMAZON COM INC",
            exchange="Nasdaq",
            cik="1018724",
        ).display_name
        == "Amazon.com, Inc."
    )
    assert (
        CompanyIdentity(
            ticker="AMAT",
            company_name="APPLIED MATERIALS INC /DE",
            exchange="Nasdaq",
            cik="6951",
        ).display_name
        == "Applied Materials Inc."
    )
