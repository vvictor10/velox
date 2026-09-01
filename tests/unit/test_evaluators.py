from __future__ import annotations

from datetime import UTC, datetime

from velox.evals.evaluators import evaluate_state
from velox.models.company import CompanyIdentity
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.failures import FallbackRecord
from velox.models.report import ApprovalStatus, EarningsBrief, ReportSection
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import RunTelemetry, SpanKind, TelemetrySpan
from velox.models.tool_result import Freshness, ToolResult
from velox.models.warnings import WarningRecord


def test_evaluate_state_passes_grounded_report_waiting_for_approval() -> None:
    evidence_pack = EvidencePack(
        records=[
            EvidenceRecord(
                evidence_id="E1",
                evidence_type=EvidenceType.EARNINGS,
                provider="fixture",
                title="earnings calendar",
            ),
            EvidenceRecord(
                evidence_id="E2",
                evidence_type=EvidenceType.SEC_FILING,
                provider="fixture",
                title="10-Q",
            ),
        ]
    )
    state = RunState(
        status=RunStatus.WAITING_FOR_APPROVAL,
        selected_ticker="AAPL",
        company=CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", cik="320193"),
        evidence_pack=evidence_pack,
        brief=EarningsBrief(
            ticker="AAPL",
            company_name="Apple Inc.",
            sections=[
                ReportSection(title="Earnings Setup", body="Date is available.", citation_ids=["E1"]),
                ReportSection(title="Risks", body="Filing risk is available.", citation_ids=["E2"]),
            ],
        ),
        telemetry=RunTelemetry(
            run_id="run-1",
            spans=[
                TelemetrySpan(name="llm.news_theme", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.delta", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.risk", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.brief_drafter", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.reviewer", kind=SpanKind.LLM).finish(),
            ],
        ),
    )

    result = evaluate_state("happy_path", state)

    assert result.passed is True
    assert result.score == 1.0


def test_evaluate_state_accepts_saved_completed_state() -> None:
    evidence_pack = EvidencePack(
        records=[
            EvidenceRecord(
                evidence_id="E1",
                evidence_type=EvidenceType.EARNINGS,
                provider="fixture",
                title="earnings calendar",
            ),
            EvidenceRecord(
                evidence_id="E2",
                evidence_type=EvidenceType.SEC_FILING,
                provider="fixture",
                title="10-Q",
            ),
        ]
    )
    state = RunState(
        status=RunStatus.COMPLETED_WITH_WARNINGS,
        approval_status=ApprovalStatus.APPROVED,
        selected_ticker="AAPL",
        company=CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", cik="320193"),
        evidence_pack=evidence_pack,
        brief=EarningsBrief(
            ticker="AAPL",
            company_name="Apple Inc.",
            sections=[
                ReportSection(title="Earnings Setup", body="Date is available.", citation_ids=["E1"]),
                ReportSection(title="Risks", body="Filing risk is available.", citation_ids=["E2"]),
            ],
        ),
        telemetry=RunTelemetry(
            run_id="run-1",
            spans=[
                TelemetrySpan(name="llm.news_theme", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.delta", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.risk", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.brief_drafter", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.reviewer", kind=SpanKind.LLM).finish(),
            ],
        ),
    )

    result = evaluate_state("saved_with_warnings", state)

    assert result.passed is True


def test_evaluate_state_accepts_visible_fallback_disclosure() -> None:
    warning = WarningRecord(
        code="fallback.news",
        message="Alpha Vantage news was unavailable; using Finnhub company news.",
        source="finnhub.company_news",
    )
    base_state = _state_with_required_report()
    state = base_state.model_copy(
        update={
            "brief": base_state.brief.model_copy(update={"warnings": [warning]}) if base_state.brief else None,
            "fallback_records": [
                FallbackRecord(
                    primary_tool_name="alpha_vantage.news_sentiment",
                    fallback_tool_name="finnhub.company_news",
                    reason="Alpha Vantage news unavailable",
                    user_message="Alpha Vantage news was unavailable; using Finnhub company news.",
                )
            ],
            "tool_results": [
                ToolResult.success(
                    tool_name="finnhub.company_news",
                    source="fixture",
                    started_at=datetime.now(UTC),
                    data=[],
                    freshness=Freshness.CURRENT,
                    fallback_used=True,
                    fallback_reason="Alpha Vantage news was unavailable; using Finnhub company news.",
                )
            ],
            "warnings": [warning],
        }
    )

    result = evaluate_state("fallback_visible", state)

    assert result.passed is True
    assert _check(result, "no_silent_fallback").passed is True


def test_evaluate_state_fails_silent_fallback() -> None:
    state = _state_with_required_report().model_copy(
        update={
            "fallback_records": [
                FallbackRecord(
                    primary_tool_name="alpha_vantage.news_sentiment",
                    fallback_tool_name="finnhub.company_news",
                    reason="Alpha Vantage news unavailable",
                    user_message="Alpha Vantage news was unavailable; using Finnhub company news.",
                )
            ]
        }
    )

    result = evaluate_state("fallback_silent", state)

    assert result.passed is False
    fallback_check = _check(result, "no_silent_fallback")
    assert fallback_check.passed is False
    assert "finnhub.company_news" in fallback_check.details


def _state_with_required_report() -> RunState:
    evidence_pack = EvidencePack(
        records=[
            EvidenceRecord(
                evidence_id="E1",
                evidence_type=EvidenceType.EARNINGS,
                provider="fixture",
                title="earnings calendar",
            ),
            EvidenceRecord(
                evidence_id="E2",
                evidence_type=EvidenceType.SEC_FILING,
                provider="fixture",
                title="10-Q",
            ),
        ]
    )
    return RunState(
        status=RunStatus.WAITING_FOR_APPROVAL,
        selected_ticker="AAPL",
        company=CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", cik="320193"),
        evidence_pack=evidence_pack,
        brief=EarningsBrief(
            ticker="AAPL",
            company_name="Apple Inc.",
            sections=[
                ReportSection(title="Earnings Setup", body="Date is available.", citation_ids=["E1"]),
                ReportSection(title="Risks", body="Filing risk is available.", citation_ids=["E2"]),
            ],
        ),
        telemetry=RunTelemetry(
            run_id="run-1",
            spans=[
                TelemetrySpan(name="llm.news_theme", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.delta", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.risk", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.brief_drafter", kind=SpanKind.LLM).finish(),
                TelemetrySpan(name="llm.reviewer", kind=SpanKind.LLM).finish(),
            ],
        ),
    )


def _check(result, name: str):
    return next(check for check in result.results if check.name == name)
