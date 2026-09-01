"""Deterministic evaluators for graph and report behavior."""

from __future__ import annotations

from pydantic import BaseModel, Field

from velox.models.state import RunState, RunStatus

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
        eval_required_report_sections(state),
        eval_valid_citations(state),
        eval_warning_disclosure(state),
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
    required = {"llm.news_theme", "llm.delta", "llm.risk", "llm.brief_drafter", "llm.reviewer"}
    if state.status == RunStatus.STOPPED and not span_names.intersection(required):
        return EvalResult(name="llm_trace_spans", passed=True, score=1.0, details="stopped before llm")
    missing = sorted(required - span_names)
    return EvalResult(
        name="llm_trace_spans",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        details=f"missing={missing}",
    )
