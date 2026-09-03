from __future__ import annotations

# ruff: noqa: I001

import re
import sys
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from velox.config import AppSettings, load_settings
from velox.models.company import CompanyIdentity
from velox.models.report import ApprovalStatus
from velox.models.state import RunState, RunStatus
from velox.models.tool_result import ToolResult, ToolStatus
from velox.providers.ticker_lookup import load_ticker_cache, search_tickers
from velox.ui import render_data
from velox.workflow.graph import stream_research_graph
from velox.workflow.nodes import save_approved_memory


st.set_page_config(page_title="Velox", page_icon="VX", layout="wide")

st.markdown(
    """
    <style>
    .velox-metric {
        min-height: 112px;
        padding: 1rem 1.05rem;
        border-radius: 0.45rem;
        background: rgba(30, 64, 175, 0.12);
        border: 1px solid rgba(59, 130, 246, 0.26);
    }
    .velox-metric-label {
        color: rgba(229, 231, 235, 0.72);
        font-size: 0.92rem;
        font-weight: 650;
        line-height: 1.2;
        margin-bottom: 0.45rem;
    }
    .velox-metric-value {
        color: #60a5fa;
        font-size: clamp(1.45rem, 2.2vw, 2.15rem);
        font-weight: 720;
        line-height: 1.08;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    .velox-metric-warning .velox-metric-value {
        color: #f59e0b;
    }
    .velox-run-meta {
        display: flex;
        justify-content: flex-end;
        gap: 1.25rem;
        color: rgba(229, 231, 235, 0.62);
        font-size: 0.88rem;
        line-height: 1.35;
        padding-top: 0.6rem;
    }
    .velox-run-meta strong {
        color: rgba(249, 250, 251, 0.82);
        font-size: 0.95rem;
        font-weight: 650;
    }
    .velox-sidebar-title {
        color: #3b82f6;
        font-size: 2.2rem;
        font-weight: 800;
        line-height: 1;
        margin: 0.35rem 0 1.4rem;
    }
    .velox-company-title {
        color: #f9fafb;
        font-size: clamp(2rem, 3.5vw, 3.4rem);
        font-weight: 800;
        line-height: 1.08;
        margin: 0.3rem 0 1.15rem;
    }
    .velox-report-title {
        color: rgba(249, 250, 251, 0.88);
        font-size: clamp(1.35rem, 2.3vw, 2.25rem);
        font-weight: 720;
        line-height: 1.16;
        margin: 1.35rem 0 1.15rem;
    }
    @keyframes velox-status-gradient {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    @keyframes velox-spinner {
        to { transform: rotate(360deg); }
    }
    .velox-progress {
        display: flex;
        align-items: center;
        gap: 0.95rem;
        min-height: 76px;
        margin-top: 0.35rem;
        padding: 1rem 1.15rem;
        border-radius: 0.5rem;
        background:
            linear-gradient(
                120deg,
                rgba(37, 99, 235, 0.28),
                rgba(20, 184, 166, 0.22),
                rgba(124, 58, 237, 0.25),
                rgba(59, 130, 246, 0.28)
            );
        background-size: 280% 280%;
        animation: velox-status-gradient 4.5s ease-in-out infinite;
        border: 1px solid rgba(96, 165, 250, 0.48);
        box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.10), 0 16px 42px rgba(15, 23, 42, 0.18);
    }
    .velox-progress-spinner {
        width: 1.2rem;
        height: 1.2rem;
        border-radius: 999px;
        border: 3px solid rgba(255, 255, 255, 0.28);
        border-top-color: #ffffff;
        flex: 0 0 auto;
        animation: velox-spinner 0.85s linear infinite;
    }
    .velox-progress-text {
        color: #f9fafb;
        font-size: 1.02rem;
        font-weight: 650;
        line-height: 1.35;
    }
    .velox-progress-log {
        margin-top: 1.25rem;
        color: rgba(229, 231, 235, 0.64);
        font-size: 0.92rem;
        line-height: 1.45;
    }
    .velox-progress-log-item {
        margin-bottom: 1.05rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

TEXT_COLUMNS = {
    "Message",
    "Summary",
    "Headline",
    "Rationale",
    "Watch Item",
    "Finding",
    "Title",
    "URL",
    "Evidence",
    "Citations",
    "Method",
    "Note",
    "Unavailable Reason",
}

TABLE_HEADER_HEIGHT = 48
TABLE_ROW_HEIGHT = 88


def _table(rows: list[dict], *, max_height: int | None = None):
    if not rows:
        return
    df = pd.DataFrame(rows)
    height: int | str = "content"
    if max_height is not None:
        content_height = TABLE_HEADER_HEIGHT + (len(df) * TABLE_ROW_HEIGHT)
        height = min(max_height, content_height)
    kwargs = {
        "hide_index": True,
        "width": "stretch",
        "height": height,
        "row_height": TABLE_ROW_HEIGHT,
        "column_config": {
            column: st.column_config.TextColumn(column, width="large")
            for column in df.columns
            if column in TEXT_COLUMNS
        },
    }
    styled = df.style.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("font-weight", "700"),
                    ("background-color", "rgba(148, 163, 184, 0.16)"),
                    ("padding", "0.7rem 0.8rem"),
                    ("line-height", "1.35"),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("padding", "0.7rem 0.8rem"),
                    ("line-height", "1.35"),
                    ("vertical-align", "middle"),
                ],
            },
        ]
    )
    st.dataframe(styled, **kwargs)


def _metric_cards(items: list[tuple[str, str, str, str | None]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, help_text, variant) in zip(columns, items, strict=True):
        with column:
            classes = "velox-metric"
            if variant:
                classes = f"{classes} velox-metric-{variant}"
            display_value = "n/a" if value in (None, "") else str(value)
            st.markdown(
                f"""
                <div class="{classes}" title="{escape(help_text)}">
                    <div class="velox-metric-label">{escape(label)}</div>
                    <div class="velox-metric-value">{escape(display_value)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


@st.cache_data(show_spinner=False)
def _load_cache():
    return load_ticker_cache()


def _run_research(ticker: str, container) -> RunState:
    settings = load_settings()
    state: RunState | None = None
    completed_messages = [_status_label(f"Selected ticker: {ticker}")]
    previous_active_text: str | None = None
    container.empty()
    with container.container():
        progress_panel = st.empty()
        progress_log = st.empty()
        _render_progress_panel(progress_panel, _status_label(f"Preparing research run for {ticker}."))
        _render_progress_log(progress_log, completed_messages)
        for state in stream_research_graph(ticker, settings):
            current_text = _status_label(state.progress_text or "Research run in progress.")
            if (
                previous_active_text
                and previous_active_text != current_text
                and previous_active_text not in completed_messages
            ):
                completed_messages.append(previous_active_text)
            for event_text in _recoverability_status_labels(state):
                if event_text not in completed_messages:
                    completed_messages.append(event_text)
            _render_progress_panel(progress_panel, current_text)
            _render_progress_log(progress_log, completed_messages)
            previous_active_text = current_text
        if state is None:
            raise RuntimeError("Research graph did not return a final state.")
        if previous_active_text and previous_active_text not in completed_messages:
            completed_messages.append(previous_active_text)
        _render_progress_log(progress_log, completed_messages)
        if state.status == RunStatus.WAITING_FOR_APPROVAL:
            _render_progress_panel(progress_panel, "Research brief ready for review", complete=True)
        else:
            _render_progress_panel(progress_panel, _status_label(state.progress_text), error=True)
    return state


def _status_label(message: str) -> str:
    return message.rstrip().rstrip(".")


def _recoverability_status_labels(state: RunState) -> list[str]:
    messages = [
        *(record.user_message for record in state.retry_records),
        *(record.user_message for record in state.fallback_records),
    ]
    return [_status_label(message) for message in messages if message]


def _render_progress_panel(slot, message: str, *, complete: bool = False, error: bool = False) -> None:
    if complete:
        slot.success(message)
        return
    if error:
        slot.error(message)
        return
    slot.markdown(
        f"""
        <div class="velox-progress">
            <div class="velox-progress-spinner"></div>
            <div class="velox-progress-text">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_progress_log(slot, messages: list[str]) -> None:
    items = "\n".join(
        f'<div class="velox-progress-log-item">{escape(message)}</div>'
        for message in messages
    )
    slot.markdown(
        f'<div class="velox-progress-log">{items}</div>',
        unsafe_allow_html=True,
    )


def _save_report(state: RunState) -> RunState:
    settings = load_settings()
    with st.status("Saving approved report memory...", expanded=True) as status:
        next_state = save_approved_memory(state, settings, approved=True)
        status.write(next_state.progress_text)
        status.update(label=next_state.progress_text, state="complete")
    return next_state


def _last_save_result(state: RunState) -> ToolResult | None:
    for result in reversed(state.tool_results):
        if result.tool_name == "mem0.save_approved_report":
            return result
    return None


def _release_date_from_headline(state: RunState) -> str | None:
    headline = state.brief.headline if state.brief and state.brief.headline else ""
    match = re.search(r"\bRelease\s+(\d{4}-\d{2}-\d{2})\b", headline, flags=re.IGNORECASE)
    if not match:
        return None
    return render_data.format_short_date(pd.to_datetime(match.group(1)).date())


def _approval_blocker(state: RunState) -> str | None:
    if state.approval_status == ApprovalStatus.APPROVED:
        return None
    if state.status != RunStatus.WAITING_FOR_APPROVAL:
        if state.reviewer_result and not state.reviewer_result.passed:
            if _revision_was_attempted(state):
                return (
                    "Reviewer blocked approval after an automatic revision attempt. "
                    "Review the findings above, then rerun the research or choose another ticker."
                )
            return (
                "Reviewer blocked approval. Review the findings above, then rerun the research "
                "or choose another ticker."
            )
        return f"Approval is unavailable while the run status is {state.status.value.replace('_', ' ')}."
    if state.brief is None:
        return "Approval is unavailable because no report brief was produced."
    if state.reviewer_result is None:
        return "Approval is unavailable because the reviewer has not evaluated the report."
    if not state.reviewer_result.passed:
        return "Reviewer blocked approval. Review the findings above, then rerun after the issue is resolved."
    return None


def _revision_was_attempted(state: RunState) -> bool:
    return sum(1 for span in state.telemetry.spans if span.name == "llm.brief_drafter") > 1 if state.telemetry else False


def _render_header(state: RunState | None, *, selected_company: CompanyIdentity | None = None) -> None:
    left, right = st.columns([0.68, 0.32], vertical_alignment="center")
    with left:
        if state and state.company:
            st.markdown(
                f'<div class="velox-company-title">{escape(state.company.ticker)} | '
                f"{escape(render_data.display_company_name(state.company.company_name, ticker=state.company.ticker))}</div>",
                unsafe_allow_html=True,
            )
        elif selected_company:
            st.markdown(
                f'<div class="velox-company-title">{escape(selected_company.ticker)} | '
                f"{escape(render_data.display_company_name(selected_company.company_name, ticker=selected_company.ticker))}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Stock earnings research agent")
    with right:
        if state:
            runtime = ""
            if state.telemetry and state.telemetry.total_duration_ms is not None:
                runtime = f"""
                <div>
                    <div>Runtime</div>
                    <strong>{state.telemetry.total_duration_ms / 1000:.1f}s</strong>
                </div>
                """
            st.markdown(
                f"""
                <div class="velox-run-meta">
                    <div>
                        <div>Run Status</div>
                        <strong>{state.status.value.replace("_", " ").title()}</strong>
                    </div>
                    {runtime}
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_picker() -> CompanyIdentity | None:
    cache = _load_cache()
    query = st.text_input("Ticker or company", placeholder="AAPL or Apple")
    matches = search_tickers(query, cache=cache) if query else []
    options = render_data.ticker_options(matches)
    option = st.selectbox(
        "Select ticker",
        options,
        index=0 if options else None,
        placeholder="Type above to search local SEC ticker cache",
    )
    if matches:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Ticker": company.ticker,
                        "Company": render_data.display_company_name(company.company_name, ticker=company.ticker),
                        "Exchange": company.exchange,
                        "CIK": company.cik,
                    }
                    for company in matches
                ]
            ),
            hide_index=True,
            width="stretch",
            row_height=36,
        )
    ticker = render_data.ticker_from_option(option)
    if ticker is None:
        return None
    return next((company for company in matches if company.ticker == ticker), None)


def _render_report(state: RunState, settings: AppSettings) -> None:
    if state.company:
        report_title = state.brief.headline if state.brief and state.brief.headline else state.company.company_name
        st.markdown(
            f'<div class="velox-report-title">{escape(report_title)}</div>',
            unsafe_allow_html=True,
        )

    if state.earnings:
        metric_items = [
            (
                label,
                value,
                "Visible tool, data, and agent warnings for this run."
                if variant == "warning"
                else "Summary metric from available earnings evidence.",
                variant,
            )
            for label, value, variant in render_data.summary_metric_items(
                state,
                release_date=_release_date_from_headline(state),
            )
        ]
        _metric_cards(
            metric_items
        )

    tabs = st.tabs(["Brief", "Earnings", "Developments", "Risks", "Sources", "Telemetry", "Evals"])

    with tabs[0]:
        if state.brief:
            for section in state.brief.sections:
                st.markdown(f"#### {section.title}")
                st.write(section.body)
                if section.citation_ids:
                    st.caption("Sources: " + ", ".join(section.citation_ids))
        else:
            st.info("No brief was produced.")
        warnings = render_data.warning_rows(state)
        if warnings:
            st.markdown("#### Warnings")
            _table(warnings, max_height=320)

        if state.reviewer_result:
            if not state.reviewer_result.passed:
                st.error("Reviewer requested revision before approval.")
                if state.reviewer_result.revision_instructions:
                    st.markdown("#### Revision Needed")
                    for instruction in state.reviewer_result.revision_instructions:
                        st.write(f"- {instruction}")
            rows = render_data.reviewer_rows(state)
            if rows:
                st.markdown("#### Reviewer Findings")
                _table(rows, max_height=260)

    with tabs[1]:
        next_rows = render_data.next_earnings_rows(state)
        if next_rows:
            _table(next_rows)
        history_rows = render_data.earnings_history_rows(state)
        if history_rows:
            _table(history_rows, max_height=380)
            surprise_rows = render_data.earnings_surprise_chart_rows(state)
            if surprise_rows:
                surprise = pd.DataFrame(surprise_rows)
                fig = go.Figure()
                colors = ["#16794c" if value >= 0 else "#c2410c" for value in surprise["EPS Surprise %"]]
                fig.add_trace(
                    go.Bar(
                        x=surprise["Period"],
                        y=surprise["EPS Surprise %"],
                        marker_color=colors,
                        text=[f"{value:.2f}%" for value in surprise["EPS Surprise %"]],
                        textposition="outside",
                        name="EPS Surprise %",
                    )
                )
                fig.add_hline(y=0, line_width=1, line_color="#6b7280")
                fig.update_layout(
                    title="Recent EPS Surprise Trend",
                    yaxis_title="EPS Surprise %",
                    xaxis_title="Period",
                    margin={"l": 32, "r": 24, "t": 48, "b": 32},
                    height=340,
                )
                st.plotly_chart(fig, width="stretch")
            eps_rows = render_data.earnings_eps_chart_rows(state)
            chart_rows = pd.DataFrame(eps_rows) if eps_rows else pd.DataFrame()
            if not chart_rows.empty:
                melted = chart_rows.melt(
                    id_vars=["Period"],
                    value_vars=["EPS Actual", "EPS Estimate"],
                    var_name="Metric",
                    value_name="EPS",
                )
                st.plotly_chart(
                    px.line(
                        melted,
                        x="Period",
                        y="EPS",
                        color="Metric",
                        markers=True,
                        title="Recent EPS Actual vs Estimate",
                    ),
                    width="stretch",
                )
        else:
            st.info("No historical earnings table is available from the gathered evidence.")

    with tabs[2]:
        prior_memory = render_data.prior_memory_rows(state)
        if prior_memory:
            st.markdown("#### Prior Report Memory")
            _table(prior_memory)
        theme_rows = render_data.news_theme_rows(state)
        if theme_rows:
            _table(theme_rows, max_height=300)
        rows = render_data.news_rows(state)
        if rows:
            _table(rows, max_height=420)
        else:
            st.info("No recent news items were available.")
        delta = render_data.delta_rows(state)
        if delta:
            st.markdown("#### What Changed")
            _table(delta, max_height=340)
        elif state.prior_memory and state.prior_memory.status.value == "found":
            st.info("Prior report memory was found; no material delta findings were produced.")

    with tabs[3]:
        rows = render_data.risk_rows(state)
        if rows:
            _table(rows, max_height=380)
        else:
            st.info("No material earnings risks were produced from the supplied evidence.")

    with tabs[4]:
        rows = render_data.source_rows(state)
        if rows:
            _table(rows, max_height=460)
        else:
            st.info("No source table is available.")

    with tabs[5]:
        if state.telemetry:
            st.markdown("#### Run Summary")
            st.caption("Runtime, status, and recovery counts from local RunState telemetry.")
            _table(render_data.telemetry_summary_rows(state))
        recovery_events = render_data.recovery_event_rows(state)
        if recovery_events:
            st.markdown("#### Recovery Events")
            st.caption("Explicit retry and fallback decisions recorded during this run.")
            _table(recovery_events, max_height=280)
        rows = render_data.telemetry_rows(state)
        if rows:
            st.markdown("#### Agent And Tool Timing")
            st.caption("Per-stage spans for graph nodes, tools, and LLM calls, including prompt version and model metadata when available.")
            _table(rows, max_height=380)
        tools = render_data.tool_rows(state)
        if tools:
            st.markdown("#### Tool Ledger")
            st.caption("Provider-level call outcomes and messages used to audit missing data, failures, retries, and fallback sources.")
            _table(tools, max_height=420)

    with tabs[6]:
        quality_summary = render_data.quality_summary_rows(state)
        if quality_summary:
            st.markdown("#### Report Quality Assessment")
            st.caption(
                "LLM-as-judge assessment of the generated research artifact, adjusted by deterministic "
                "guardrails and RunState telemetry. This is not investment confidence."
            )
            _table(quality_summary, max_height=220)
        quality_factors = render_data.quality_factor_rows(state)
        if quality_factors:
            st.markdown("#### Quality Factors Considered")
            st.caption(
                "Factors include evidence support, ticker relevance, risk specificity, missing-data handling, "
                "clarity, safety boundary, deterministic pass rate, data coverage, recovery transparency, "
                "reviewer status, and memory context."
            )
            _table(quality_factors, max_height=420)
        improvement_rows = render_data.quality_improvement_rows(state)
        if improvement_rows:
            st.markdown("#### Quality Improvement Notes")
            _table(improvement_rows, max_height=220)
        st.markdown("#### LangSmith Trace")
        st.caption(
            "External trace context for inspecting graph, tool, and LLM spans in LangSmith. "
            "The deterministic checks below are local pass/fail evals, not model confidence or investment confidence. "
            "LangSmith tracing: "
            f"{'Enabled' if settings.langsmith_enabled else 'Disabled'} | "
            f"Project: {settings.langsmith_project} | Run ID: {state.run_id}"
        )
        eval_rows = render_data.eval_checklist_rows(state)
        if eval_rows:
            st.markdown("#### Deterministic Guardrail Checks")
            st.caption(
                "Binary code-based checks for objective constraints: evidence contract, citations, warning visibility, "
                "recovery visibility, approval boundary, expected LLM spans, and basic advice-boundary terms."
            )
            _table(eval_rows, max_height=420)


def main() -> None:
    settings = load_settings()
    state: RunState | None = st.session_state.get("run_state")
    header_panel = st.empty()
    main_panel = st.empty()
    selected_company: CompanyIdentity | None = None

    with st.sidebar:
        st.markdown('<div class="velox-sidebar-title">Velox</div>', unsafe_allow_html=True)
        selected_company = _render_picker()
        run_clicked = st.button("Run Research", disabled=selected_company is None, width="stretch")
        if run_clicked and selected_company:
            st.session_state["run_state"] = None
            st.session_state["pending_ticker"] = selected_company.ticker
            st.session_state["pending_company"] = selected_company.model_dump()
            st.rerun()

        st.divider()
        st.header("System Status")
        _table(render_data.startup_rows(settings), max_height=300)

    pending_ticker = st.session_state.get("pending_ticker")
    if pending_ticker:
        pending_company = CompanyIdentity.model_validate(st.session_state.get("pending_company"))
        with header_panel.container():
            _render_header(None, selected_company=pending_company)
        try:
            st.session_state["run_state"] = _run_research(str(pending_ticker), main_panel)
        finally:
            st.session_state.pop("pending_ticker", None)
            st.session_state.pop("pending_company", None)
        st.rerun()

    state = st.session_state.get("run_state")
    with header_panel.container():
        _render_header(state, selected_company=selected_company)
    if state is None:
        with main_panel.container():
            st.info("Search for a U.S. ticker to start an earnings research run.")
        return

    with main_panel.container():
        _render_report(state, settings)

        save_result = _last_save_result(state)
        if state.approval_status == ApprovalStatus.APPROVED and save_result and save_result.status == ToolStatus.SUCCESS:
            st.markdown("#### Human Review Gate")
            st.success("Approved report saved to memory.")
            return

        st.markdown("#### Human Review Gate")
        st.caption(
            "The agent can research, draft, and review on its own, but it cannot save report memory "
            "until you approve the reviewed brief."
        )
        can_save = (
            state.status in {RunStatus.WAITING_FOR_APPROVAL, RunStatus.COMPLETED_WITH_WARNINGS}
            and state.brief is not None
            and state.reviewer_result is not None
            and state.reviewer_result.passed
            and state.approval_status != ApprovalStatus.APPROVED
        )
        blocker = None if can_save else _approval_blocker(state)
        if save_result and save_result.status != ToolStatus.SUCCESS:
            st.error(save_result.error or "Report memory save failed. You can retry the save.")
        if blocker:
            st.warning(blocker)
        if st.button(
            "Retry Save Report" if save_result and save_result.status != ToolStatus.SUCCESS else "Approve & Save Report",
            disabled=not can_save,
            type="primary",
            width="stretch",
            help=blocker,
        ):
            st.session_state["run_state"] = _save_report(state)
            st.rerun()


if __name__ == "__main__":
    main()
