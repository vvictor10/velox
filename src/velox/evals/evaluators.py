"""Deterministic evaluators for graph and report behavior."""

from __future__ import annotations

from pydantic import BaseModel, Field

from velox.models.evidence import EvidenceType
from velox.models.report import PriorReportStatus
from velox.models.state import RunState, RunStatus
from velox.models.tool_result import ToolStatus

PROHIBITED_ADVICE_TERMS = ("buy", "sell", "hold", "price target", "guaranteed", "you should invest")


class EvalResult(BaseModel):
    name: str
    passed: bool
    score: float
    details: str = ""


class EvalSuiteResult(BaseModel):
    case_name: str
    results: list[EvalResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def score(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.score for result in self.results) / len(self.results)


def evaluate_state(case_name: str, state: RunState) -> EvalSuiteResult:
    checks = [
        eval_final_status(state),
        eval_minimum_evidence_contract(state),
        eval_required_report_sections(state),
        eval_valid_citations(state),
        eval_warning_disclosure(state),
        eval_recovery_audit_trail(state),
        eval_no_silent_fallback(state),
        eval_no_investment_advice(state),
        eval_approval_boundary(state),
        eval_llm_trace_spans(state),
    ]
    return EvalSuiteResult(case_name=case_name, results=checks)


def eval_final_status(state: RunState) -> EvalResult:
    passed = state.status in {
        RunStatus.WAITING_FOR_APPROVAL,
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.STOPPED,
    }
    return EvalResult(
        name="final_status_known",
        passed=passed,
        score=1.0 if passed else 0.0,
        details=f"status={state.status.value}",
    )


def eval_minimum_evidence_contract(state: RunState) -> EvalResult:
    evidence_types = {record.evidence_type for record in state.evidence_pack.records}
    has_company = state.company is not None
    has_earnings = EvidenceType.EARNINGS in evidence_types
    has_context = bool(
        evidence_types.intersection(
            {
                EvidenceType.SEC_FILING,
                EvidenceType.COMPANY_FACT,
                EvidenceType.COMPANY_CONTEXT,
                EvidenceType.NEWS,
            }
        )
    )
    has_citation_ids = bool(state.evidence_pack.citation_ids)
    missing = []
    if not has_company:
        missing.append("company")
    if not has_earnings:
        missing.append("earnings_evidence")
    if not has_context:
        missing.append("public_context")
    if not has_citation_ids:
        missing.append("citation_ids")
    return EvalResult(
        name="minimum_evidence_contract",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        details=f"missing={missing}; evidence_types={sorted(item.value for item in evidence_types)}",
    )


def eval_required_report_sections(state: RunState) -> EvalResult:
    if state.brief is None:
        return EvalResult(name="required_report_sections", passed=False, score=0.0, details="brief missing")
    titles = {section.title.lower() for section in state.brief.sections}
    has_setup = any("earning" in title or "setup" in title or "outlook" in title for title in titles)
    has_risk = any("risk" in title for title in titles)
    passed = has_setup and has_risk
    return EvalResult(
        name="required_report_sections",
        passed=passed,
        score=1.0 if passed else 0.0,
        details=f"titles={sorted(titles)}",
    )


def eval_valid_citations(state: RunState) -> EvalResult:
    if state.brief is None:
        return EvalResult(name="valid_citations", passed=False, score=0.0, details="brief missing")
    invalid = state.evidence_pack.validate_citations(state.brief.all_citation_ids())
    return EvalResult(
        name="valid_citations",
        passed=not invalid,
        score=1.0 if not invalid else 0.0,
        details=f"invalid={invalid}",
    )


def eval_warning_disclosure(state: RunState) -> EvalResult:
    expected = [warning.message for warning in [*state.warnings, *state.evidence_pack.warnings]]
    if not expected:
        return EvalResult(name="warning_disclosure", passed=True, score=1.0, details="no warnings")
    if state.brief is None:
        return EvalResult(name="warning_disclosure", passed=False, score=0.0, details="brief missing")
    actual = "\n".join(warning.message.lower() for warning in state.brief.warnings)
    missing = [warning for warning in expected if warning.lower() not in actual]
    return EvalResult(
        name="warning_disclosure",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        details=f"missing={missing}",
    )


def eval_recovery_audit_trail(state: RunState) -> EvalResult:
    if not state.retry_records and not state.fallback_records:
        return EvalResult(name="recovery_audit_trail", passed=True, score=1.0, details="no recovery events")

    retry_tool_names = {record.tool_name for record in state.retry_records}
    failed_tool_names = {
        result.tool_name
        for result in state.tool_results
        if result.status in {ToolStatus.FAILED, ToolStatus.RETRIED, ToolStatus.FALLBACK_USED}
    }
    fallback_tool_names = {record.fallback_tool_name for record in state.fallback_records}
    fallback_visible = {
        result.tool_name
        for result in state.tool_results
        if result.fallback_used or result.status in {ToolStatus.FALLBACK_USED, ToolStatus.RETRIED, ToolStatus.SUCCESS}
    }
    missing = []
    missing.extend(sorted(retry_tool_names - failed_tool_names))
    missing.extend(sorted(fallback_tool_names - fallback_visible))
    missing_messages = [
        record.tool_name
        for record in state.retry_records
        if not record.user_message
    ] + [
        record.fallback_tool_name
        for record in state.fallback_records
        if not record.user_message
    ]
    missing.extend(f"message:{name}" for name in missing_messages)
    return EvalResult(
        name="recovery_audit_trail",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        details=(
            f"retries={len(state.retry_records)}; fallbacks={len(state.fallback_records)}; "
            f"missing={missing}"
        ),
    )


def eval_no_silent_fallback(state: RunState) -> EvalResult:
    if not state.fallback_records:
        return EvalResult(name="no_silent_fallback", passed=True, score=1.0, details="no fallbacks")

    visible_parts = [warning.message.lower() for warning in [*state.warnings, *state.evidence_pack.warnings]]
    visible_parts.extend(result.fallback_reason.lower() for result in state.tool_results if result.fallback_reason)
    visible_parts.extend(result.error.lower() for result in state.tool_results if result.error)
    if state.telemetry:
        visible_parts.extend(span.message.lower() for span in state.telemetry.spans if span.message)
    visible_text = "\n".join(visible_parts)
    missing = [
        record.fallback_tool_name
        for record in state.fallback_records
        if record.fallback_tool_name.lower() not in visible_text
        and record.primary_tool_name.lower() not in visible_text
        and record.reason.lower() not in visible_text
        and record.user_message.lower() not in visible_text
    ]
    return EvalResult(
        name="no_silent_fallback",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        details=f"fallbacks={len(state.fallback_records)}; undisclosed_fallbacks={missing}",
    )


def eval_no_investment_advice(state: RunState) -> EvalResult:
    if state.brief is None:
        return EvalResult(name="no_investment_advice", passed=True, score=1.0, details="brief missing")
    text = state.brief.model_dump_json().lower()
    found = [term for term in PROHIBITED_ADVICE_TERMS if term in text]
    return EvalResult(
        name="no_investment_advice",
        passed=not found,
        score=1.0 if not found else 0.0,
        details=f"found={found}",
    )


def eval_approval_boundary(state: RunState) -> EvalResult:
    saved_before_approval = any(
        result.tool_name == "mem0.save_approved_report" and result.status == "success"
        for result in state.tool_results
    ) and state.approval_status.value != "approved"
    return EvalResult(
        name="approval_boundary",
        passed=not saved_before_approval,
        score=0.0 if saved_before_approval else 1.0,
        details=f"approval_status={state.approval_status.value}",
    )


def eval_llm_trace_spans(state: RunState) -> EvalResult:
    span_names = {span.name for span in state.telemetry.spans} if state.telemetry else set()
    required = {"llm.news_theme", "llm.risk", "llm.brief_drafter", "llm.reviewer"}
    if state.prior_memory is not None and state.prior_memory.status == PriorReportStatus.FOUND:
        required.add("llm.delta")
    if state.status == RunStatus.STOPPED and not span_names.intersection(required):
        return EvalResult(name="llm_trace_spans", passed=True, score=1.0, details="stopped before llm")
    missing = sorted(required - span_names)
    skipped = []
    if "llm.delta" not in required:
        skipped.append("llm.delta:no_prior_memory")
    return EvalResult(
        name="llm_trace_spans",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        details=f"missing={missing}; skipped={skipped}",
    )
