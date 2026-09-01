from __future__ import annotations

from datetime import UTC, datetime

import pytest

from velox.config import AppSettings
from velox.models.company import CompanyIdentity, TickerCache, TickerCacheMetadata
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.failures import FallbackRecord
from velox.models.report import (
    ApprovalStatus,
    EarningsBrief,
    PriorReportMemory,
    PriorReportStatus,
    ReportSection,
)
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult
from velox.providers.normalization import normalize_earnings_snapshot, normalize_news_snapshot
from velox.providers.research_data import PublicDataBundle
from velox.workflow import nodes
from velox.workflow.graph import build_minimal_graph, initial_state_for_ticker


def test_minimal_graph_reaches_waiting_for_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    cache = TickerCache(
        metadata=TickerCacheMetadata(source_url="fixture", record_count=1),
        companies=[company],
    )
    evidence_pack = EvidencePack(
        records=[
            EvidenceRecord(
                evidence_type=EvidenceType.EARNINGS,
                provider="Finnhub /calendar/earnings",
                title="finnhub.earnings_calendar",
                payload={"earningsCalendar": [{"date": "2026-10-29", "symbol": "AAPL"}]},
            ),
            EvidenceRecord(
                evidence_type=EvidenceType.SEC_FILING,
                provider="SEC EDGAR submissions",
                title="sec.submissions",
            ),
        ]
    ).assign_ids()
    tool_results = [
        ToolResult.success(
            tool_name="sec.submissions",
            source="SEC EDGAR submissions",
            started_at=datetime.now(UTC),
            data={"cik": "320193"},
        )
    ]
    bundle = PublicDataBundle(
        company=company,
        tool_results=tool_results,
        evidence_pack=evidence_pack,
        earnings=normalize_earnings_snapshot("AAPL", evidence_pack),
        news=normalize_news_snapshot("AAPL", evidence_pack),
        fallback_records=[
            FallbackRecord(
                primary_tool_name="alpha_vantage.news_sentiment",
                fallback_tool_name="finnhub.company_news",
                reason="Alpha disabled.",
                user_message="Alpha Vantage news was unavailable; using Finnhub company news.",
            )
        ],
        warnings=[],
    )

    monkeypatch.setattr(nodes, "load_ticker_cache", lambda: cache)
    monkeypatch.setattr(nodes, "collect_public_data", lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(nodes, "Mem0ReportStore", lambda _settings: _FakeStore())

    app = build_minimal_graph(AppSettings())
    output = RunState.model_validate(app.invoke(initial_state_for_ticker("AAPL", AppSettings())))

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.company == company
    assert output.evidence_pack.citation_ids == {"E1", "E2"}
    assert output.fallback_records[0].fallback_tool_name == "finnhub.company_news"
    assert output.prior_memory and output.prior_memory.status == PriorReportStatus.MISSING


def test_minimal_graph_stops_for_unknown_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = TickerCache(
        metadata=TickerCacheMetadata(source_url="fixture", record_count=0),
        companies=[],
    )
    monkeypatch.setattr(nodes, "load_ticker_cache", lambda: cache)

    app = build_minimal_graph(AppSettings())
    output = RunState.model_validate(app.invoke(initial_state_for_ticker("NOPE", AppSettings())))

    assert output.status == RunStatus.STOPPED
    assert output.warnings[0].code == "ticker.unsupported"


def test_minimal_graph_invocation_works_with_tracing_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    cache = TickerCache(
        metadata=TickerCacheMetadata(source_url="fixture", record_count=1),
        companies=[company],
    )
    evidence_pack = EvidencePack(
        records=[
            EvidenceRecord(
                evidence_type=EvidenceType.EARNINGS,
                provider="Finnhub /calendar/earnings",
                title="finnhub.earnings_calendar",
                payload={"earningsCalendar": [{"date": "2026-10-29", "symbol": "AAPL"}]},
            ),
            EvidenceRecord(
                evidence_type=EvidenceType.SEC_FILING,
                provider="SEC EDGAR submissions",
                title="sec.submissions",
            ),
        ]
    ).assign_ids()
    bundle = PublicDataBundle(
        company=company,
        tool_results=[
            ToolResult.success(
                tool_name="sec.submissions",
                source="SEC EDGAR submissions",
                started_at=datetime.now(UTC),
                data={"cik": "320193"},
            )
        ],
        evidence_pack=evidence_pack,
        earnings=normalize_earnings_snapshot("AAPL", evidence_pack),
        news=normalize_news_snapshot("AAPL", evidence_pack),
        warnings=[],
    )

    monkeypatch.setattr(nodes, "load_ticker_cache", lambda: cache)
    monkeypatch.setattr(nodes, "collect_public_data", lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(nodes, "Mem0ReportStore", lambda _settings: _FakeStore())

    from velox.workflow.graph import invoke_minimal_graph

    output = invoke_minimal_graph("AAPL", AppSettings(langsmith_tracing=False))

    assert output.status == RunStatus.WAITING_FOR_APPROVAL


def test_load_memory_lookup_failure_continues_with_visible_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    failing_store = _FakeStore(
        memory=PriorReportMemory(
            ticker="AAPL",
            cik="320193",
            status=PriorReportStatus.LOOKUP_FAILED,
        ),
        lookup_result=ToolResult.failure(
            tool_name="mem0.lookup_prior_report",
            source="Mem0",
            started_at=datetime.now(UTC),
            status="lookup_failed",
            failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            error="Mem0 lookup failed.",
        ),
    )
    monkeypatch.setattr(nodes, "Mem0ReportStore", lambda _settings: failing_store)

    output = nodes.make_load_memory_node(AppSettings())(RunState(company=company, selected_ticker="AAPL"))

    assert output.status != RunStatus.STOPPED
    assert output.prior_memory and output.prior_memory.status == PriorReportStatus.LOOKUP_FAILED
    assert output.progress_text == "Continuing without prior report memory because Mem0 lookup failed."


def test_load_memory_missing_report_is_neutral_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    missing_store = _FakeStore(
        memory=PriorReportMemory(
            ticker="AAPL",
            cik="320193",
            status=PriorReportStatus.MISSING,
        ),
        lookup_result=ToolResult.success(
            tool_name="mem0.lookup_prior_report",
            source="Mem0 not_found",
            started_at=datetime.now(UTC),
            data={"strategy": "not_found"},
        ),
    )
    monkeypatch.setattr(nodes, "Mem0ReportStore", lambda _settings: missing_store)

    output = nodes.make_load_memory_node(AppSettings())(RunState(company=company, selected_ticker="AAPL"))

    assert output.prior_memory and output.prior_memory.status == PriorReportStatus.MISSING
    assert output.progress_text == "No prior approved report memory found."
    assert not output.warnings


def test_save_memory_refuses_without_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    state = RunState(
        selected_ticker="AAPL",
        company=company,
        brief=EarningsBrief(
            ticker="AAPL",
            company_name="Apple Inc.",
            sections=[ReportSection(title="Summary", body="Approved report.", citation_ids=[])],
        ),
    )
    monkeypatch.setattr(nodes, "Mem0ReportStore", lambda _settings: _FakeStore())

    output = nodes.save_approved_memory(state, AppSettings(), approved=False)

    assert output.tool_results[-1].status == "skipped"
    assert "approval is required" in (output.tool_results[-1].error or "")


def test_save_memory_marks_completed_after_approved_save(monkeypatch: pytest.MonkeyPatch) -> None:
    company = CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")
    state = RunState(
        selected_ticker="AAPL",
        company=company,
        brief=EarningsBrief(
            ticker="AAPL",
            company_name="Apple Inc.",
            sections=[ReportSection(title="Summary", body="Approved report.", citation_ids=[])],
        ),
    )
    monkeypatch.setattr(nodes, "Mem0ReportStore", lambda _settings: _FakeStore())

    output = nodes.save_approved_memory(state, AppSettings(), approved=True)

    assert output.status == RunStatus.COMPLETED
    assert output.approval_status == ApprovalStatus.APPROVED
    assert output.tool_results[-1].status == "success"
    assert output.prior_memory and output.prior_memory.status == PriorReportStatus.FOUND


class _FakeStore:
    def __init__(
        self,
        memory: PriorReportMemory | None = None,
        lookup_result: ToolResult | None = None,
    ) -> None:
        self.memory = memory or PriorReportMemory(
            ticker="AAPL",
            cik="320193",
            status=PriorReportStatus.MISSING,
        )
        self.lookup_result = lookup_result or ToolResult.success(
            tool_name="mem0.lookup_prior_report",
            source="Mem0",
            started_at=datetime.now(UTC),
            data={"results": []},
        )

    def lookup_prior_report(self, _company):
        return self.memory, self.lookup_result

    def save_approved_report(self, *, company, brief, approved, existing_memory_id=None):
        from velox.providers.mem0_store import MemorySaveResult

        if not approved:
            return MemorySaveResult(
                memory=PriorReportMemory(
                    ticker=company.ticker,
                    cik=company.cik,
                    status=PriorReportStatus.NOT_CHECKED,
                ),
                tool_result=ToolResult.failure(
                    tool_name="mem0.save_approved_report",
                    source="Mem0",
                    started_at=datetime.now(UTC),
                    status="skipped",
                    failure_category=FailureCategory.NON_RECOVERABLE,
                    error="User approval is required before saving report memory.",
                ),
            )
        return MemorySaveResult(
            memory=PriorReportMemory(
                ticker=company.ticker,
                cik=company.cik,
                status=PriorReportStatus.FOUND,
                summary=brief.sections[0].body,
            ),
            tool_result=ToolResult.success(
                tool_name="mem0.save_approved_report",
                source="Mem0",
                started_at=datetime.now(UTC),
                data={"id": existing_memory_id or "mem-1"},
            ),
        )
