from __future__ import annotations

from velox.evals.evaluators import evaluate_state
from velox.models.company import CompanyIdentity
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.report import ApprovalStatus, EarningsBrief, ReportSection
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import RunTelemetry, SpanKind, TelemetrySpan


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
