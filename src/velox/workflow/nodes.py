"""Node implementations for the Velox workflow."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from velox.analysis.llm_client import LlmCallResult, LlmProvider, VeloxLlmClient
from velox.analysis.prompts import PromptTemplate, load_prompt
from velox.analysis.schemas import (
    BriefOutput,
    DeltaOutput,
    NewsThemeOutput,
    ReviewerOutput,
    RiskOutput,
)
from velox.config import AppSettings
from velox.models.evidence import EvidenceRecord
from velox.models.report import (
    ApprovalStatus,
    DeltaFinding,
    EarningsBrief,
    PriorReportStatus,
    ReportSection,
    ReviewerFinding,
    ReviewerResult,
    RiskFinding,
)
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import FailureCategory, SpanKind, SpanStatus, TelemetrySpan
from velox.models.tool_result import ToolStatus
from velox.models.warnings import WarningRecord, WarningSeverity
from velox.observability import traceable_step
from velox.providers.mem0_store import Mem0ReportStore
from velox.providers.research_data import PublicDataBundle, collect_public_data
from velox.providers.ticker_lookup import load_ticker_cache
from velox.workflow import progress


def ensure_state(state: RunState | dict) -> RunState:
    return state if isinstance(state, RunState) else RunState.model_validate(state)


def resolve_company_identity_node(state: RunState | dict) -> RunState:
    current = ensure_state(state).touch(
        progress_text=progress.RESOLVING_COMPANY,
        status=RunStatus.RUNNING,
    )
    if not current.selected_ticker:
        return _stop_with_warning(
            current,
            code="ticker.missing",
            message="No ticker was selected.",
        )

    ticker = current.selected_ticker.upper()
    cache = load_ticker_cache()
    company = next((company for company in cache.companies if company.ticker == ticker), None)
    if company is None:
        return _stop_with_warning(
            current,
            code="ticker.unsupported",
            message=f"{ticker} was not found in the local SEC ticker cache.",
        )

    return current.model_copy(
        update={
            "company": company,
            "selected_ticker": company.ticker,
            "updated_at": current.updated_at,
            "progress_text": progress.COLLECTING_EVIDENCE,
            "status": RunStatus.RUNNING,
        }
    )


def make_collect_evidence_node(settings: AppSettings):
    def collect_evidence_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.COLLECTING_EVIDENCE)
        if current.company is None:
            return _stop_with_warning(
                current,
                code="company.identity_missing",
                message="Company identity was not resolved before evidence collection.",
            )

        span = TelemetrySpan(name="collect_public_data", kind=SpanKind.TOOL)
        bundle = collect_public_data(current.company, settings)
        finished_span = span.finish(SpanStatus.SUCCESS)
        telemetry = current.telemetry
        if telemetry is not None:
            telemetry.add_span(finished_span)

        return _state_from_public_data_bundle(current, bundle).touch(
            progress_text=_public_data_progress(bundle),
            status=RunStatus.RUNNING,
        )

    return collect_evidence_node


def make_load_memory_node(settings: AppSettings):
    def load_memory_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.LOADING_MEMORY)
        if current.company is None:
            return _stop_with_warning(
                current,
                code="company.identity_missing",
                message="Company identity was not resolved before prior-memory lookup.",
            )

        store = Mem0ReportStore(settings)
        traced_lookup = traceable_step(
            name="mem0.lookup_prior_report",
            run_type="tool",
            metadata={"tool_name": "mem0.lookup_prior_report"},
            settings=settings,
        )(lambda: store.lookup_prior_report(current.company))
        memory, tool_result = traced_lookup()
        next_state = current.add_tool_result(tool_result).model_copy(update={"prior_memory": memory})
        if tool_result.status == ToolStatus.LOOKUP_FAILED:
            return next_state.touch(progress_text=progress.MEMORY_LOOKUP_FAILED)
        if memory.status.value == "found":
            return next_state.touch(progress_text=progress.MEMORY_FOUND)
        return next_state.touch(progress_text=progress.MEMORY_NOT_FOUND)

    return load_memory_node


def minimum_evidence_gate_node(state: RunState | dict) -> RunState:
    current = ensure_state(state)
    has_identity = current.company is not None
    has_earnings = bool(
        current.earnings
        and (current.earnings.has_forward_calendar or current.earnings.has_historical_earnings)
    )
    has_context = any(
        result.status == "success" and result.tool_name.startswith("sec.")
        for result in current.tool_results
    )

    if has_identity and has_earnings and has_context:
        return current.touch(
            progress_text=progress.MINIMUM_EVIDENCE_MET,
            status=RunStatus.WAITING_FOR_APPROVAL,
        )

    return _stop_with_warning(
        current,
        code="evidence.minimum_not_met",
        message=(
            "Minimum evidence was not met. Velox needs company identity, earnings evidence, "
            "and public company context before drafting a grounded report."
        ),
        progress_text=progress.MINIMUM_EVIDENCE_FAILED,
    )


def make_news_theme_node(settings: AppSettings):
    def news_theme_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.ANALYZING_NEWS)
        prompt = load_prompt("news_theme")
        result = _call_llm_with_retry(
            current,
            settings,
            model_id=settings.velox_news_theme_model,
            prompt=prompt,
            user_payload=_news_theme_payload(current),
            output_schema=NewsThemeOutput,
        )
        current = _state_with_llm_telemetry(current, result)
        if not result.schema_valid or result.output is None:
            return _continue_with_warning(
                current,
                code="llm.news_theme.schema_invalid",
                message=(
                    result.error
                    or "News theme analysis returned invalid structured output; continuing without generated news themes."
                ),
                progress_text="Continuing without generated news themes because structured output validation failed.",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            ).model_copy(update={"news_themes": []})
        news_theme_output = NewsThemeOutput.model_validate(result.output)
        next_progress = (
            progress.ANALYZING_DELTA
            if _has_prior_report_memory(current)
            else progress.SKIPPING_DELTA_NO_MEMORY
        )
        return current.model_copy(
            update={"news_themes": [theme.model_dump() for theme in news_theme_output.themes]}
        ).touch(progress_text=next_progress, status=RunStatus.RUNNING)

    return news_theme_node


def make_delta_node(settings: AppSettings):
    def delta_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.ANALYZING_DELTA)
        prompt = load_prompt("delta")
        result = _call_llm_with_retry(
            current,
            settings,
            model_id=settings.velox_delta_model,
            prompt=prompt,
            user_payload=_delta_payload(current),
            output_schema=DeltaOutput,
        )
        current = _state_with_llm_telemetry(current, result)
        if not result.schema_valid or result.output is None:
            return _continue_with_warning(
                current,
                code="llm.delta.schema_invalid",
                message=(
                    result.error
                    or "Delta analysis returned invalid structured output; continuing without prior-report comparison."
                ),
                progress_text="Continuing without delta comparison because structured output validation failed.",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            ).model_copy(update={"delta_findings": []})
        delta_output = DeltaOutput.model_validate(result.output)
        return current.model_copy(
            update={
                "delta_findings": [
                    DeltaFinding.model_validate(finding.model_dump())
                    for finding in delta_output.findings
                ]
            }
        ).touch(progress_text=progress.ANALYZING_RISK, status=RunStatus.RUNNING)

    return delta_node


def make_risk_node(settings: AppSettings):
    def risk_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.ANALYZING_RISK)
        prompt = load_prompt("risk")
        result = _call_llm_with_retry(
            current,
            settings,
            model_id=settings.velox_risk_model,
            prompt=prompt,
            user_payload=_risk_payload(current),
            output_schema=RiskOutput,
        )
        current = _state_with_llm_telemetry(current, result)
        if not result.schema_valid or result.output is None:
            return _continue_with_warning(
                current,
                code="llm.risk.schema_invalid",
                message=(
                    result.error
                    or "Risk analysis returned invalid structured output; continuing without generated risk findings."
                ),
                progress_text="Continuing without generated risk findings because structured output validation failed.",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            ).model_copy(update={"risk_findings": []})
        risk_output = RiskOutput.model_validate(result.output)
        return current.model_copy(
            update={
                "risk_findings": [
                    RiskFinding(
                        risk=finding.risk,
                        severity=finding.severity.value,
                        rationale=finding.rationale,
                        supporting_evidence_ids=finding.supporting_evidence_ids,
                        watch_item=finding.watch_item,
                    )
                    for finding in risk_output.risks
                ]
            }
        ).touch(progress_text=progress.DRAFTING_BRIEF, status=RunStatus.RUNNING)

    return risk_node


def make_brief_drafter_node(settings: AppSettings):
    def brief_drafter_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.DRAFTING_BRIEF)
        if current.company is None:
            return _stop_with_warning(
                current,
                code="company.identity_missing",
                message="Company identity was not resolved before brief drafting.",
            )
        prompt = load_prompt("brief_drafter")
        return _draft_brief(current, settings, prompt=prompt)

    return brief_drafter_node


def _draft_brief(
    current: RunState,
    settings: AppSettings,
    *,
    prompt: PromptTemplate,
    progress_text: str = progress.REVIEWING_BRIEF,
) -> RunState:
    result = _call_llm_with_retry(
        current,
        settings,
        model_id=settings.velox_brief_model,
        prompt=prompt,
        user_payload=_brief_payload(current),
        output_schema=BriefOutput,
    )
    current = _state_with_llm_telemetry(current, result)
    if not result.schema_valid or result.output is None:
        return _stop_with_warning(
            current,
            code="llm.brief_drafter.schema_invalid",
            message=result.error or "Brief drafting returned invalid structured output.",
            progress_text="Stopping because brief drafting returned invalid structured output.",
            failure_category=FailureCategory.RECOVERABLE,
        )
    brief_output = BriefOutput.model_validate(result.output)
    section_citation_ids = [
        citation_id
        for section in brief_output.sections
        for citation_id in section.citation_ids
    ]
    invalid_citations = current.evidence_pack.validate_citations(
        [*brief_output.source_ids_used, *section_citation_ids]
    )
    if invalid_citations:
        return _stop_with_warning(
            current,
            code="llm.brief_drafter.invalid_citations",
            message=f"Brief used unknown citation IDs: {', '.join(invalid_citations)}.",
            progress_text="Stopping because the draft used unknown citation IDs.",
            failure_category=FailureCategory.RECOVERABLE,
        )
    brief = EarningsBrief(
        ticker=current.company.ticker,
        company_name=current.company.company_name,
        headline=brief_output.headline,
        sections=[
            ReportSection.model_validate(section.model_dump())
            for section in brief_output.sections
        ],
        warnings=_dedupe_warnings([*current.warnings, *current.evidence_pack.warnings]),
        prompt_versions={prompt.name: prompt.version},
        model_ids={prompt.name: result.model_id},
    )
    return current.model_copy(update={"brief": brief}).touch(
        progress_text=progress_text,
        status=RunStatus.RUNNING,
    )


def make_reviewer_node(settings: AppSettings):
    def reviewer_node(state: RunState | dict) -> RunState:
        current = ensure_state(state).touch(progress_text=progress.REVIEWING_BRIEF)
        if current.brief is None:
            return _stop_with_warning(
                current,
                code="brief.missing",
                message="No draft brief exists to review.",
            )
        prompt = load_prompt("reviewer")
        result = _call_llm_with_retry(
            current,
            settings,
            model_id=settings.velox_reviewer_model,
            prompt=prompt,
            user_payload=_reviewer_payload(current),
            output_schema=ReviewerOutput,
        )
        current = _state_with_llm_telemetry(current, result)
        if not result.schema_valid or result.output is None:
            return _stop_with_warning(
                current,
                code="llm.reviewer.schema_invalid",
                message=result.error or "Reviewer returned invalid structured output.",
                progress_text="Stopping because reviewer returned invalid structured output.",
                failure_category=FailureCategory.RECOVERABLE,
            )
        reviewer_output = ReviewerOutput.model_validate(result.output)
        reviewer_result = ReviewerResult(
            passed=reviewer_output.passed,
            findings=[
                ReviewerFinding(
                    code=finding.code,
                    message=finding.message,
                    severity=finding.severity.value,
                    citation_ids=finding.citation_ids,
                    requires_revision=finding.requires_revision,
                )
                for finding in reviewer_output.findings
            ],
            revision_instructions=reviewer_output.revision_instructions,
        )
        next_state = current.model_copy(update={"reviewer_result": reviewer_result})
        review_retried = False
        if not reviewer_result.passed and _can_auto_repair_citations(reviewer_result):
            repaired_state = _repair_section_citation_arrays(next_state)
            if repaired_state is not next_state:
                review_retried = True
                retry_result = _call_llm_with_retry(
                    repaired_state,
                    settings,
                    model_id=settings.velox_reviewer_model,
                    prompt=prompt,
                    user_payload=_reviewer_payload(repaired_state),
                    output_schema=ReviewerOutput,
                )
                repaired_state = _state_with_llm_telemetry(repaired_state, retry_result)
                if retry_result.schema_valid and retry_result.output is not None:
                    retry_output = ReviewerOutput.model_validate(retry_result.output)
                    reviewer_result = ReviewerResult(
                        passed=retry_output.passed,
                        findings=[
                            ReviewerFinding(
                                code=finding.code,
                                message=finding.message,
                                severity=finding.severity.value,
                                citation_ids=finding.citation_ids,
                                requires_revision=finding.requires_revision,
                            )
                            for finding in retry_output.findings
                        ],
                        revision_instructions=retry_output.revision_instructions,
                    )
                    next_state = repaired_state.model_copy(update={"reviewer_result": reviewer_result})
        if (
            not review_retried
            and not reviewer_result.passed
            and _can_auto_revise_brief(reviewer_result)
        ):
            draft_prompt = load_prompt("brief_drafter")
            revision_state = next_state.touch(
                progress_text=progress.REVISING_BRIEF,
                status=RunStatus.RUNNING,
            )
            revised_state = _draft_brief(
                revision_state,
                settings,
                prompt=draft_prompt,
                progress_text=progress.REVIEWING_BRIEF,
            )
            if revised_state.status != RunStatus.STOPPED:
                retry_result = _call_llm_with_retry(
                    revised_state,
                    settings,
                    model_id=settings.velox_reviewer_model,
                    prompt=prompt,
                    user_payload=_reviewer_payload(revised_state),
                    output_schema=ReviewerOutput,
                )
                revised_state = _state_with_llm_telemetry(revised_state, retry_result)
                if retry_result.schema_valid and retry_result.output is not None:
                    retry_output = ReviewerOutput.model_validate(retry_result.output)
                    reviewer_result = ReviewerResult(
                        passed=retry_output.passed,
                        findings=[
                            ReviewerFinding(
                                code=finding.code,
                                message=finding.message,
                                severity=finding.severity.value,
                                citation_ids=finding.citation_ids,
                                requires_revision=finding.requires_revision,
                            )
                            for finding in retry_output.findings
                        ],
                        revision_instructions=retry_output.revision_instructions,
                    )
                    next_state = revised_state.model_copy(update={"reviewer_result": reviewer_result})
        if not reviewer_result.passed or reviewer_result.requires_revision:
            return next_state.touch(
                progress_text=progress.REVIEW_FAILED,
                status=RunStatus.STOPPED,
            )
        if next_state.brief is not None:
            next_state.brief.prompt_versions[prompt.name] = prompt.version
            next_state.brief.model_ids[prompt.name] = result.model_id
        return next_state.touch(
            progress_text=progress.WAITING_FOR_APPROVAL,
            status=RunStatus.WAITING_FOR_APPROVAL,
        )

    return reviewer_node


def _can_auto_revise_brief(reviewer_result: ReviewerResult) -> bool:
    if not reviewer_result.findings:
        return False
    revision_required = [finding for finding in reviewer_result.findings if finding.requires_revision]
    return bool(revision_required)


def _can_auto_repair_citations(reviewer_result: ReviewerResult) -> bool:
    if not reviewer_result.findings:
        return False
    repairable = [finding for finding in reviewer_result.findings if finding.requires_revision]
    if not repairable:
        return False
    return all(_is_citation_metadata_finding(finding) for finding in repairable)


def _is_citation_metadata_finding(finding: ReviewerFinding) -> bool:
    text = f"{finding.code} {finding.message}".lower()
    unsafe_terms = ("price target", "recommendation", "buy", "sell", "hold", "unsupported")
    return "citation" in text and not any(term in text for term in unsafe_terms)


def _repair_section_citation_arrays(state: RunState) -> RunState:
    if state.brief is None:
        return state
    valid_ids = state.evidence_pack.citation_ids
    sections: list[ReportSection] = []
    changed = False
    for section in state.brief.sections:
        mentioned_ids = [
            evidence_id
            for evidence_id in re.findall(r"\bE\d+\b", section.body)
            if evidence_id in valid_ids
        ]
        citation_ids = list(dict.fromkeys([*section.citation_ids, *mentioned_ids]))
        if citation_ids != section.citation_ids:
            changed = True
        sections.append(section.model_copy(update={"citation_ids": citation_ids}))
    if not changed:
        return state
    brief = state.brief.model_copy(update={"sections": sections})
    return state.model_copy(update={"brief": brief}).touch(
        progress_text=progress.REPAIRING_CITATIONS,
        status=RunStatus.RUNNING,
    )


def save_approved_memory(
    state: RunState | dict,
    settings: AppSettings,
    *,
    approved: bool,
) -> RunState:
    current = ensure_state(state)
    if current.company is None:
        return _stop_with_warning(
            current,
            code="company.identity_missing",
            message="Company identity was not resolved before memory save.",
        )
    if current.brief is None:
        return _stop_with_warning(
            current,
            code="brief.missing",
            message="No report brief exists to save.",
        )

    store = Mem0ReportStore(settings)
    traced_save = traceable_step(
        name="mem0.save_approved_report",
        run_type="tool",
        metadata={"tool_name": "mem0.save_approved_report", "approved": approved},
        settings=settings,
    )(
        lambda: store.save_approved_report(
            company=current.company,
            brief=current.brief,
            approved=approved,
            existing_memory_id=current.prior_memory.memory_id if current.prior_memory else None,
            previous_memory=current.prior_memory,
        )
    )
    save_result = traced_save()
    next_state = current.add_tool_result(save_result.tool_result).model_copy(
        update={
            "prior_memory": save_result.memory,
        }
    )
    if save_result.tool_result.status == ToolStatus.SUCCESS:
        return next_state.model_copy(update={"approval_status": ApprovalStatus.APPROVED}).touch(
            progress_text="Approved report memory saved.",
            status=RunStatus.COMPLETED_WITH_WARNINGS
            if next_state.completed_with_warnings()
            else RunStatus.COMPLETED,
        )
    if approved and save_result.saved_snapshot_path is not None:
        return next_state.touch(
            progress_text=save_result.tool_result.error,
            status=RunStatus.COMPLETED_WITH_WARNINGS,
        )
    return next_state.touch(progress_text=save_result.tool_result.error)


def _call_llm_with_retry(
    _state: RunState,
    settings: AppSettings,
    *,
    model_id: str | None,
    prompt: PromptTemplate,
    user_payload: dict[str, Any],
    output_schema: type[BaseModel],
    max_attempts: int = 2,
) -> LlmCallResult:
    if model_id is None:
        return _missing_llm_result(prompt)

    provider = _provider_for_model(model_id)
    client = VeloxLlmClient(settings)
    last_result: LlmCallResult | None = None
    for attempt in range(1, max_attempts + 1):
        result = client.call_structured(
            provider=provider,
            model_id=model_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            system_prompt=prompt.body,
            user_payload=user_payload,
            output_schema=output_schema,
            max_tokens=_max_tokens_for_prompt(prompt.name),
        )
        result.telemetry.retry_count = attempt - 1
        last_result = result
        if result.schema_valid:
            return result

    return last_result or _missing_llm_result(prompt)


def _missing_llm_result(prompt: PromptTemplate) -> LlmCallResult:
    span = TelemetrySpan(
        name=f"llm.{prompt.name}",
        kind=SpanKind.LLM,
        status=SpanStatus.FAILED,
        failure_category=FailureCategory.NON_RECOVERABLE,
        prompt_version=prompt.version,
        model_id="missing",
        message="No pinned model was configured.",
    ).finish(SpanStatus.FAILED)
    return LlmCallResult(
        provider=LlmProvider.NEBIUS,
        model_id="missing",
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        schema_valid=False,
        error=f"No pinned model configured for {prompt.name}.",
        telemetry=span,
    )


def _max_tokens_for_prompt(prompt_name: str) -> int:
    return {
        "news_theme": 1200,
        "delta": 2400,
        "risk": 1600,
        "brief_drafter": 2600,
        "reviewer": 1400,
    }.get(prompt_name, 1200)


def _provider_for_model(model_id: str) -> LlmProvider:
    if model_id.startswith("accounts/fireworks/"):
        return LlmProvider.FIREWORKS
    return LlmProvider.NEBIUS


def _state_with_llm_telemetry(state: RunState, result: LlmCallResult) -> RunState:
    if state.telemetry is not None:
        state.telemetry.add_span(result.telemetry)
    return state


def _news_theme_payload(state: RunState) -> dict[str, Any]:
    return {
        "ticker": state.selected_ticker,
        "evidence": _news_evidence_payloads(state, max_payload_chars=1200),
    }


def _delta_payload(state: RunState) -> dict[str, Any]:
    return {
        "ticker": state.selected_ticker,
        "prior_report_status": state.prior_memory.status.value if state.prior_memory else "not_checked",
        "prior_report_summary": state.prior_memory.summary if state.prior_memory else None,
        "prior_report_payload": state.prior_memory.payload if state.prior_memory else {},
        "current_evidence": [
            _evidence_payload(record, max_payload_chars=1200)
            for record in state.evidence_pack.records
        ],
    }


def _risk_payload(state: RunState) -> dict[str, Any]:
    return {
        "ticker": state.selected_ticker,
        "evidence": _analysis_evidence_payloads(state, max_payload_chars=1200),
        "news_themes": state.news_themes,
        "delta_findings": [finding.model_dump() for finding in state.delta_findings],
        "warnings": _warning_messages(state),
    }


def _brief_payload(state: RunState) -> dict[str, Any]:
    payload = {
        "ticker": state.selected_ticker,
        "company_name": state.company.display_name if state.company else None,
        "evidence": _analysis_evidence_payloads(state, max_payload_chars=1200),
        "news_themes": state.news_themes,
        "delta_findings": [finding.model_dump() for finding in state.delta_findings],
        "risk_findings": [finding.model_dump() for finding in state.risk_findings],
        "warnings": _warning_messages(state),
    }
    if state.reviewer_result is not None and not state.reviewer_result.passed:
        payload["revision_request"] = {
            "instructions": state.reviewer_result.revision_instructions,
            "findings": [
                {
                    "code": finding.code,
                    "message": finding.message,
                    "severity": finding.severity,
                    "citation_ids": finding.citation_ids,
                    "requires_revision": finding.requires_revision,
                }
                for finding in state.reviewer_result.findings
            ],
            "previous_draft": state.brief.model_dump(mode="json") if state.brief else None,
        }
    return payload


def _reviewer_payload(state: RunState) -> dict[str, Any]:
    return {
        "ticker": state.selected_ticker,
        "evidence_ids": sorted(state.evidence_pack.citation_ids),
        "tool_warnings": _warning_messages(state),
        "draft": state.brief.model_dump(mode="json") if state.brief else None,
    }


def _evidence_payload(record: EvidenceRecord, *, max_payload_chars: int) -> dict[str, Any]:
    return {
        "evidence_id": record.evidence_id,
        "type": record.evidence_type.value,
        "provider": record.provider,
        "title": record.title,
        "source_url": record.source_url,
        "source_date": record.source_date.isoformat() if record.source_date else None,
        "captured_at": record.captured_at.isoformat(),
        "freshness": record.freshness.value,
        "payload": _compact_payload(record.payload, max_chars=max_payload_chars),
    }


def _analysis_evidence_payloads(state: RunState, *, max_payload_chars: int) -> list[dict[str, Any]]:
    records = [
        _evidence_payload(record, max_payload_chars=max_payload_chars)
        for record in state.evidence_pack.records
        if record.evidence_type.value != "news"
    ]
    return [*records, *_news_evidence_payloads(state, max_payload_chars=max_payload_chars)]


def _news_evidence_payloads(state: RunState, *, max_payload_chars: int) -> list[dict[str, Any]]:
    if state.news is None:
        return [
            _evidence_payload(record, max_payload_chars=max_payload_chars)
            for record in state.evidence_pack.records
            if record.evidence_type.value == "news"
        ]
    return [
        {
            "evidence_id": item.source_evidence_id,
            "type": "news",
            "provider": item.source_provider,
            "title": item.headline,
            "source_url": item.url,
            "source_date": item.published_at.isoformat(),
            "captured_at": item.captured_at.isoformat(),
            "freshness": "current",
            "payload": _compact_payload(item.model_dump(mode="json"), max_chars=max_payload_chars),
        }
        for item in state.news.items
    ]


def _warning_messages(state: RunState) -> list[str]:
    return [warning.message for warning in _dedupe_warnings([*state.warnings, *state.evidence_pack.warnings])]


def _dedupe_warnings(warnings: list[WarningRecord]) -> list[WarningRecord]:
    seen: set[tuple[str, str]] = set()
    deduped: list[WarningRecord] = []
    for warning in warnings:
        key = (warning.code, warning.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _compact_payload(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    text = json.dumps(payload, default=str, ensure_ascii=True)
    if len(text) <= max_chars:
        return payload
    return {
        "_truncated": True,
        "text": text[:max_chars],
        "original_char_count": len(text),
    }


def _state_from_public_data_bundle(state: RunState, bundle: PublicDataBundle) -> RunState:
    return state.model_copy(
        update={
            "tool_results": [*state.tool_results, *bundle.tool_results],
            "evidence_pack": bundle.evidence_pack,
            "earnings": bundle.earnings,
            "news": bundle.news,
            "warnings": [*state.warnings, *bundle.warnings],
            "retry_records": [*state.retry_records, *bundle.retry_records],
            "fallback_records": [*state.fallback_records, *bundle.fallback_records],
        }
    )


def _public_data_progress(bundle: PublicDataBundle) -> str:
    if bundle.fallback_records:
        return bundle.fallback_records[-1].user_message
    if bundle.retry_records:
        return bundle.retry_records[-1].user_message
    if bundle.completed_with_warnings:
        return "Evidence collected with warnings; assembling citations."
    return progress.ASSEMBLING_EVIDENCE


def _has_prior_report_memory(state: RunState) -> bool:
    return state.prior_memory is not None and state.prior_memory.status == PriorReportStatus.FOUND


def _stop_with_warning(
    state: RunState,
    *,
    code: str,
    message: str,
    progress_text: str | None = None,
    failure_category: FailureCategory | None = None,
) -> RunState:
    warning = WarningRecord(
        code=code,
        message=message,
        severity=WarningSeverity.ERROR,
        failure_category=failure_category,
    )
    return state.model_copy(
        update={
            "warnings": [*state.warnings, warning],
            "progress_text": progress_text or message,
            "status": RunStatus.STOPPED,
        }
    )


def _continue_with_warning(
    state: RunState,
    *,
    code: str,
    message: str,
    progress_text: str,
    failure_category: FailureCategory,
) -> RunState:
    warning = WarningRecord(
        code=code,
        message=message,
        severity=WarningSeverity.WARNING,
        failure_category=failure_category,
    )
    return state.model_copy(
        update={
            "warnings": [*state.warnings, warning],
            "progress_text": progress_text,
            "status": RunStatus.RUNNING,
        }
    )
