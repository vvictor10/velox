from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from velox.analysis.llm_client import LlmCallResult, LlmProvider
from velox.config import AppSettings
from velox.models.company import CompanyIdentity, TickerCache, TickerCacheMetadata
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.report import PriorReportMemory, PriorReportStatus
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import SpanKind, TelemetrySpan
from velox.models.tool_result import ToolResult
from velox.providers.normalization import normalize_earnings_snapshot, normalize_news_snapshot
from velox.providers.research_data import PublicDataBundle
from velox.workflow import nodes
from velox.workflow.graph import (
    build_research_graph,
    initial_state_for_ticker,
    invoke_research_graph,
    stream_research_graph,
)


def test_research_graph_reaches_approval_after_reviewer_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_foundation(monkeypatch)
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: _FakeLlmClient())

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.news_themes
    assert output.delta_findings
    assert output.risk_findings
    assert output.brief is not None
    assert output.brief.model_ids["brief_drafter"] == "accounts/fireworks/models/gpt-oss-120b"
    assert output.reviewer_result and output.reviewer_result.passed is True
    assert output.telemetry
    assert output.telemetry.final_status == "waiting_for_approval"
    assert {span.name for span in output.telemetry.spans} >= {
        "llm.news_theme",
        "llm.delta",
        "llm.risk",
        "llm.brief_drafter",
        "llm.reviewer",
    }


def test_research_graph_streams_progress_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: _FakeLlmClient())

    updates = list(stream_research_graph("AAPL", _settings()))

    assert updates[-1].status == RunStatus.WAITING_FOR_APPROVAL
    assert "Collecting earnings, SEC, news, and fallback evidence." in {
        update.progress_text for update in updates
    }
    assert "Finding earnings-relevant news themes." in {
        update.progress_text for update in updates
    }


def test_llm_node_retries_once_after_invalid_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(invalid_first_stage="risk")
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    app = build_research_graph(_settings())
    output = RunState.model_validate(app.invoke(initial_state_for_ticker("AAPL", _settings())))

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    risk_span = next(span for span in output.telemetry.spans if span.name == "llm.risk")
    assert risk_span.retry_count == 1
    assert fake_client.calls_by_prompt["risk"] == 2


def test_delta_failure_continues_with_visible_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(always_invalid_stage="delta")
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.delta_findings == []
    assert any(warning.code == "llm.delta.schema_invalid" for warning in output.warnings)
    assert fake_client.calls_by_prompt["delta"] == 2


def test_news_theme_failure_continues_with_visible_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(always_invalid_stage="news_theme")
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.news_themes == []
    assert any(warning.code == "llm.news_theme.schema_invalid" for warning in output.warnings)
    assert output.brief is not None


def test_risk_failure_continues_with_visible_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(always_invalid_stage="risk")
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.risk_findings == []
    assert any(warning.code == "llm.risk.schema_invalid" for warning in output.warnings)
    assert output.brief is not None


def test_reviewer_failure_stops_before_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(reviewer_passes=False)
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    app = build_research_graph(_settings())
    output = RunState.model_validate(app.invoke(initial_state_for_ticker("AAPL", _settings())))

    assert output.status == RunStatus.STOPPED
    assert output.progress_text == "Reviewer found issues that need revision before approval."
    assert output.reviewer_result
    assert output.reviewer_result.requires_revision is True
    assert fake_client.calls_by_prompt["brief_drafter"] == 2
    assert fake_client.calls_by_prompt["reviewer"] == 2


def test_reviewer_content_failure_auto_revises_then_reaches_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(reviewer_content_failure_once=True)
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.reviewer_result and output.reviewer_result.passed is True
    assert fake_client.calls_by_prompt["brief_drafter"] == 2
    assert fake_client.calls_by_prompt["reviewer"] == 2


def test_reviewer_citation_metadata_failure_is_auto_repaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(
        reviewer_citation_failure_once=True,
        brief_missing_section_citations=True,
    )
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.WAITING_FOR_APPROVAL
    assert output.reviewer_result and output.reviewer_result.passed is True
    data_gaps = next(section for section in output.brief.sections if section.title == "Data Gaps")
    assert data_gaps.citation_ids == ["E2", "E3"]
    assert fake_client.calls_by_prompt["reviewer"] == 2


def test_brief_section_invalid_citation_stops_before_review(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_foundation(monkeypatch)
    fake_client = _FakeLlmClient(brief_invalid_section_citation=True)
    monkeypatch.setattr(nodes, "VeloxLlmClient", lambda _settings: fake_client)

    output = invoke_research_graph("AAPL", _settings())

    assert output.status == RunStatus.STOPPED
    assert output.reviewer_result is None
    assert any(warning.code == "llm.brief_drafter.invalid_citations" for warning in output.warnings)


def _settings() -> AppSettings:
    return AppSettings(
        langsmith_tracing=False,
        velox_news_theme_model="accounts/fireworks/models/gpt-oss-120b",
        velox_delta_model="openai/gpt-oss-120b",
        velox_risk_model="accounts/fireworks/models/gpt-oss-120b",
        velox_brief_model="accounts/fireworks/models/gpt-oss-120b",
        velox_reviewer_model="openai/gpt-oss-120b",
    )


def _patch_foundation(monkeypatch: pytest.MonkeyPatch) -> None:
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
                evidence_type=EvidenceType.NEWS,
                provider="Finnhub company news",
                title="Company launches AI product",
                payload={"headline": "Company launches AI product before earnings"},
            ),
            EvidenceRecord(
                evidence_type=EvidenceType.SEC_FILING,
                provider="SEC EDGAR submissions",
                title="sec.submissions",
                payload={"note": "Management discussed margin pressure."},
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


class _FakeStore:
    def lookup_prior_report(self, _company):
        return (
            PriorReportMemory(
                ticker="AAPL",
                cik="320193",
                status=PriorReportStatus.FOUND,
                summary="Prior report focused on services growth.",
            ),
            ToolResult.success(
                tool_name="mem0.lookup_prior_report",
                source="Mem0",
                started_at=datetime.now(UTC),
                data={"results": [{"id": "mem-1"}]},
            ),
        )


class _FakeLlmClient:
    def __init__(
        self,
        *,
        invalid_first_stage: str | None = None,
        always_invalid_stage: str | None = None,
        reviewer_passes: bool = True,
        reviewer_citation_failure_once: bool = False,
        reviewer_content_failure_once: bool = False,
        brief_missing_section_citations: bool = False,
        brief_invalid_section_citation: bool = False,
    ) -> None:
        self.invalid_first_stage = invalid_first_stage
        self.always_invalid_stage = always_invalid_stage
        self.reviewer_passes = reviewer_passes
        self.reviewer_citation_failure_once = reviewer_citation_failure_once
        self.reviewer_content_failure_once = reviewer_content_failure_once
        self.brief_missing_section_citations = brief_missing_section_citations
        self.brief_invalid_section_citation = brief_invalid_section_citation
        self.calls_by_prompt: dict[str, int] = {}

    def call_structured(
        self,
        *,
        provider: LlmProvider,
        model_id: str,
        prompt_name: str,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: type,
        max_tokens: int,
    ) -> LlmCallResult:
        self.calls_by_prompt[prompt_name] = self.calls_by_prompt.get(prompt_name, 0) + 1
        call_count = self.calls_by_prompt[prompt_name]
        if self.always_invalid_stage == prompt_name or (
            self.invalid_first_stage == prompt_name and call_count == 1
        ):
            return _llm_result(
                provider,
                model_id,
                prompt_name,
                prompt_version,
                schema_valid=False,
                output=None,
                error="Invalid JSON.",
            )
        return _llm_result(
            provider,
            model_id,
            prompt_name,
            prompt_version,
            output=self._output_for_prompt(prompt_name, call_count),
        )

    def _output_for_prompt(self, prompt_name: str, call_count: int) -> dict[str, Any]:
        if prompt_name == "brief_drafter" and self.brief_missing_section_citations:
            output = _output_for_prompt(prompt_name, self.reviewer_passes)
            output["sections"].append(
                {
                    "title": "Data Gaps",
                    "body": "The current evidence references E2 and E3, but data coverage remains incomplete.",
                    "citation_ids": [],
                }
            )
            output["source_ids_used"] = ["E1", "E2", "E3"]
            return output
        if prompt_name == "brief_drafter" and self.brief_invalid_section_citation:
            output = _output_for_prompt(prompt_name, self.reviewer_passes)
            output["sections"][0]["citation_ids"] = ["E999"]
            output["source_ids_used"] = ["E1"]
            return output
        if prompt_name == "reviewer" and self.reviewer_citation_failure_once and call_count == 1:
            return {
                "passed": False,
                "findings": [
                    {
                        "code": "citation.missing",
                        "message": (
                            "The Data Gaps section references evidence IDs E2 and E3 in the text "
                            "but does not include them in the citation_ids array."
                        ),
                        "severity": "high",
                        "citation_ids": ["E2", "E3"],
                        "requires_revision": True,
                    }
                ],
                "revision_instructions": [
                    "In the Data Gaps section, update citation_ids to include E2 and E3."
                ],
            }
        if prompt_name == "reviewer" and self.reviewer_content_failure_once and call_count == 1:
            return {
                "passed": False,
                "findings": [
                    {
                        "code": "unsupported_interpretation",
                        "message": "The brief infers market expectations not directly supported by evidence.",
                        "severity": "high",
                        "citation_ids": ["E2"],
                        "requires_revision": True,
                    }
                ],
                "revision_instructions": [
                    "Remove the unsupported market-expectations interpretation or tie it directly to evidence."
                ],
            }
        return _output_for_prompt(prompt_name, self.reviewer_passes)


def _output_for_prompt(prompt_name: str, reviewer_passes: bool) -> dict[str, Any]:
    outputs = {
        "news_theme": {
            "themes": [
                {
                    "theme": "AI product launch",
                    "summary": "Recent news highlights an AI product launch.",
                    "supporting_evidence_ids": ["E2"],
                    "confidence": 0.8,
                }
            ],
            "missing_data_notes": [],
        },
        "delta": {
            "findings": [
                {
                    "category": "new",
                    "finding": "AI product launch is newly prominent.",
                    "supporting_evidence_ids": ["E2"],
                }
            ],
            "prior_report_status": "found",
            "missing_data_notes": [],
        },
        "risk": {
            "risks": [
                {
                    "risk": "Margin pressure",
                    "severity": "medium",
                    "rationale": "Management discussed margin pressure in the filing.",
                    "supporting_evidence_ids": ["E3"],
                    "watch_item": "Watch gross margin commentary.",
                }
            ],
            "missing_data_notes": [],
        },
        "brief_drafter": {
            "headline": "Apple earnings preview",
            "sections": [
                {
                    "title": "Earnings Setup",
                    "body": "The earnings calendar lists the next report date.",
                    "citation_ids": ["E1"],
                },
                {
                    "title": "Risks",
                    "body": "Margin pressure remains a watch item.",
                    "citation_ids": ["E3"],
                },
            ],
            "warnings": [],
            "source_ids_used": ["E1", "E3"],
        },
        "reviewer": {
            "passed": reviewer_passes,
            "findings": []
            if reviewer_passes
            else [
                {
                    "code": "MISSING_CITATION",
                    "message": "A key claim is missing a citation.",
                    "severity": "high",
                    "citation_ids": [],
                    "requires_revision": True,
                }
            ],
            "revision_instructions": [] if reviewer_passes else ["Add citations before approval."],
        },
    }
    return outputs[prompt_name]


def _llm_result(
    provider: LlmProvider,
    model_id: str,
    prompt_name: str,
    prompt_version: str,
    *,
    output: dict[str, Any] | None = None,
    schema_valid: bool = True,
    error: str | None = None,
) -> LlmCallResult:
    return LlmCallResult(
        provider=provider,
        model_id=model_id,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        output=output,
        schema_valid=schema_valid,
        error=error,
        telemetry=TelemetrySpan(
            name=f"llm.{prompt_name}",
            kind=SpanKind.LLM,
            provider=provider.value,
            model_id=model_id,
            prompt_version=prompt_version,
        ).finish(),
    )
