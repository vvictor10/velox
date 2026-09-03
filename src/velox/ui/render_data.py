"""Render-friendly table data derived from Velox state models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from velox.evals.evaluators import evaluate_state
from velox.models.company import friendly_company_name
from velox.models.state import RunState

TEXT_LIMIT = 220
RECENT_EARNINGS_HISTORY_LIMIT = 4


def ticker_options(state_companies) -> list[str]:
    return [
        f"{company.ticker} | {display_company_name(company.company_name, ticker=company.ticker)}"
        for company in state_companies
    ]


def ticker_from_option(option: str | None) -> str | None:
    if not option:
        return None
    return option.split("|", 1)[0].strip().upper()


def startup_rows(settings) -> list[dict[str, str]]:
    return clean_rows(
        [
            {
                "Name": check.name,
                "Status": format_label(check.status),
                "Message": compact_text(check.message),
            }
            for check in settings.startup_checks()
        ]
    )


def display_company_name(company_name: str | None, *, ticker: str | None = None) -> str:
    return friendly_company_name(company_name, ticker=ticker)


def tool_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "Tool": result.tool_name,
            "Status": format_label(result.status.value),
            "Category": format_label(result.failure_category.value),
            "Duration": format_seconds(result.duration_ms),
            "Source": result.source,
            "Freshness": format_label(result.freshness.value),
            "Fallback": result.fallback_used,
            "Message": compact_text(result.error or result.fallback_reason or ""),
        }
        for result in state.tool_results
    ]
    return clean_rows(rows)


def warning_rows(state: RunState) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    warnings = []
    for warning in [*state.warnings, *state.evidence_pack.warnings]:
        key = (warning.code, warning.message)
        if key in seen:
            continue
        seen.add(key)
        warnings.append(warning)
    rows = [
        {
            "Issue": _warning_issue(warning.code),
            "Severity": format_label(warning.severity.value),
            "Source": warning.source or "",
            "Message": compact_text(warning.message),
        }
        for warning in warnings
    ]
    return clean_rows(rows)


def prior_memory_rows(state: RunState) -> list[dict[str, Any]]:
    if state.prior_memory is None:
        return []
    memory = state.prior_memory
    if not memory.summary and not memory.memory_id:
        return []
    rows = [
        {
            "Ticker": memory.ticker,
            "Status": format_label(memory.status.value),
            "Memory ID": memory.memory_id or "",
            "Report Timestamp": format_date(memory.report_timestamp),
            "Summary Available": bool(memory.summary),
        }
    ]
    return clean_rows(rows)


def source_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "ID": row.evidence_id,
            "Type": format_label(row.evidence_type.value),
            "Provider": row.provider,
            "Source Date": format_date(row.source_date),
            "Captured": format_date(row.captured_at),
            "Title": compact_text(row.title, limit=140),
            "URL": row.source_url or "",
        }
        for row in state.evidence_pack.source_table()
    ]
    return clean_rows(rows)


def news_theme_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "Theme": compact_text(str(theme.get("theme", "")), limit=140),
            "Summary": compact_text(str(theme.get("summary", ""))),
            "Supporting Evidence IDs": ", ".join(
                str(item) for item in theme.get("supporting_evidence_ids", [])
            ),
            "Confidence": format_decimal(theme.get("confidence")),
        }
        for theme in state.news_themes
    ]
    return clean_rows(rows)


def earnings_history_rows(state: RunState) -> list[dict[str, Any]]:
    if state.earnings is None:
        return []
    rows = [
        {
            "Period": format_date(item.period),
            "Fiscal Q": item.fiscal_quarter,
            "Fiscal Year": item.fiscal_year,
            "EPS Actual": format_eps(item.eps_actual),
            "EPS Estimate": format_eps(item.eps_estimate),
            "Revenue Actual": format_money_millions(item.revenue_actual),
            "Revenue Estimate": format_money_millions(item.revenue_estimate),
            "EPS Surprise %": format_percent(item.surprise_percent),
            "Source": item.source_provider,
            "Evidence": item.source_evidence_id,
        }
        for item in _recent_earnings_history(state)
    ]
    return clean_rows(rows)


def latest_earnings_summary(state: RunState) -> dict[str, Any]:
    if state.earnings is None or not state.earnings.history:
        return {}
    dated = [item for item in state.earnings.history if item.period is not None]
    latest = max(dated, key=lambda item: item.period) if dated else state.earnings.history[0]
    rows = clean_rows(
        [
            {
                "Period": format_short_date(latest.period),
                "EPS Actual": format_eps(latest.eps_actual),
                "EPS Estimate": format_eps(latest.eps_estimate),
                "EPS Surprise %": format_percent(latest.surprise_percent),
                "Revenue Actual": format_money(latest.revenue_actual),
                "Revenue Estimate": format_money(latest.revenue_estimate),
            }
        ]
    )
    return rows[0] if rows else {}


def summary_metric_items(state: RunState, *, release_date: str | None = None) -> list[tuple[str, str, str | None]]:
    latest = latest_earnings_summary(state)
    event = state.earnings.next_event if state.earnings else None
    items: list[tuple[str, str, str | None]] = []

    if event and event.report_date:
        items.append(("Next Report", format_short_date(event.report_date), None))
    elif release_date:
        items.append(("Release Date", release_date, None))
    elif latest.get("Period"):
        items.append(("Latest Quarter", str(latest["Period"]), None))

    if event and event.eps_estimate is not None:
        items.append(("EPS Estimate", format_eps(event.eps_estimate), None))
    elif latest.get("EPS Actual"):
        items.append(("Latest EPS Actual", str(latest["EPS Actual"]), None))

    if event and event.revenue_estimate is not None:
        items.append(("Revenue Estimate", format_money(event.revenue_estimate), None))
    elif latest.get("Revenue Actual"):
        items.append(("Latest Revenue", str(latest["Revenue Actual"]), None))
    elif latest.get("EPS Surprise %"):
        items.append(("EPS Surprise", str(latest["EPS Surprise %"]), None))

    items.append(("Warnings", str(len(warning_rows(state))), "warning"))
    return items


def earnings_surprise_chart_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "Period": format_date(item.period),
            "EPS Surprise %": item.surprise_percent,
        }
        for item in _recent_earnings_history(state)
        if item.period is not None and item.surprise_percent is not None
    ]
    return list(reversed(rows))


def earnings_eps_chart_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "Period": format_date(item.period),
            "EPS Actual": item.eps_actual,
            "EPS Estimate": item.eps_estimate,
        }
        for item in _recent_earnings_history(state)
        if item.period is not None and (item.eps_actual is not None or item.eps_estimate is not None)
    ]
    return list(reversed(rows))


def _recent_earnings_history(state: RunState):
    if state.earnings is None:
        return []
    dated = [item for item in state.earnings.history if item.period is not None]
    undated = [item for item in state.earnings.history if item.period is None]
    by_period = {}
    for item in dated:
        existing = by_period.get(item.period)
        if existing is None or _history_completeness(item) > _history_completeness(existing):
            by_period[item.period] = item
    return [
        *sorted(by_period.values(), key=lambda item: item.period, reverse=True),
        *undated,
    ][:RECENT_EARNINGS_HISTORY_LIMIT]


def _history_completeness(item) -> int:
    return sum(
        value is not None
        for value in (
            item.eps_actual,
            item.eps_estimate,
            item.revenue_actual,
            item.revenue_estimate,
            item.surprise,
            item.surprise_percent,
        )
    )


def next_earnings_rows(state: RunState) -> list[dict[str, Any]]:
    if state.earnings is None or state.earnings.next_event is None:
        return []
    event = state.earnings.next_event
    rows = [
        {
            "Report Date": format_date(event.report_date),
            "Timing": format_label(event.timing.value),
            "Fiscal Q": event.fiscal_quarter,
            "Fiscal Year": event.fiscal_year,
            "EPS Estimate": format_eps(event.eps_estimate),
            "Revenue Estimate": format_money_millions(event.revenue_estimate),
            "Source": event.source_provider,
            "Evidence": event.source_evidence_id,
        }
    ]
    return clean_rows(rows)


def news_rows(state: RunState) -> list[dict[str, Any]]:
    if state.news is None:
        return []
    rows = [
        {
            "Published": format_date(item.published_at),
            "Source": item.source,
            "Headline": compact_text(item.headline),
            "Summary": compact_text(item.summary or ""),
            "Evidence": item.source_evidence_id,
            "URL": item.url or "",
        }
        for item in state.news.items
    ]
    return clean_rows(rows)


def risk_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "Risk": compact_text(risk.risk, limit=140),
            "Severity": risk.severity,
            "Rationale": compact_text(risk.rationale),
            "Watch Item": compact_text(risk.watch_item or ""),
            "Evidence": ", ".join(risk.supporting_evidence_ids),
        }
        for risk in state.risk_findings
    ]
    return clean_rows(rows)


def delta_rows(state: RunState) -> list[dict[str, Any]]:
    rows = [
        {
            "Category": format_label(finding.category.value),
            "Finding": compact_text(finding.finding),
            "Evidence": ", ".join(finding.supporting_evidence_ids),
        }
        for finding in state.delta_findings
    ]
    return clean_rows(rows)


def reviewer_rows(state: RunState) -> list[dict[str, Any]]:
    if state.reviewer_result is None:
        return []
    rows = [
        {
            "Code": finding.code,
            "Severity": finding.severity,
            "Requires Revision": finding.requires_revision,
            "Message": compact_text(finding.message),
            "Citations": ", ".join(finding.citation_ids),
        }
        for finding in state.reviewer_result.findings
    ]
    return clean_rows(rows)


def telemetry_rows(state: RunState) -> list[dict[str, Any]]:
    if state.telemetry is None:
        return []
    rows = [
        {
            "Span": span.name,
            "Kind": format_label(span.kind.value),
            "Status": format_label(span.status.value),
            "Duration": format_seconds(span.duration_ms),
            "Provider": span.provider or "",
            "Model": span.model_id or "",
            "Prompt": span.prompt_version or "",
            "Retries": span.retry_count,
            "Fallback": span.fallback_used,
        }
        for span in state.telemetry.spans
    ]
    return clean_rows(rows)


def telemetry_summary_rows(state: RunState) -> list[dict[str, Any]]:
    if state.telemetry is None:
        return []
    summary = state.telemetry.public_summary()
    return clean_rows(
        [
            {
                "Final Status": summary.get("final_status") or "",
                "Completed With Warnings": summary.get("completed_with_warnings"),
                "Total Runtime": format_seconds(summary.get("total_duration_ms")),
                "Tool Retries": len(state.retry_records),
                "Tool Fallbacks": len(state.fallback_records),
                "LLM Retries": summary.get("retry_count"),
                "Slowest Span": summary.get("slowest_span") or "",
                "Slowest Duration": format_seconds(summary.get("slowest_span_duration_ms")),
            }
        ]
    )


def recovery_event_rows(state: RunState) -> list[dict[str, Any]]:
    retry_rows = [
        {
            "Event": "Retry",
            "Primary Tool": record.tool_name,
            "Fallback Tool": "",
            "Attempt": str(record.attempt_count),
            "Category": format_label(record.failure_category.value),
            "Message": compact_text(record.user_message),
            "Reason": compact_text(record.reason),
            "Timestamp": format_date(record.created_at),
        }
        for record in state.retry_records
    ]
    fallback_rows = [
        {
            "Event": "Fallback",
            "Primary Tool": record.primary_tool_name,
            "Fallback Tool": record.fallback_tool_name,
            "Attempt": "",
            "Category": "",
            "Message": compact_text(record.user_message),
            "Reason": compact_text(record.reason),
            "Timestamp": format_date(record.created_at),
        }
        for record in state.fallback_records
    ]
    return clean_rows([*retry_rows, *fallback_rows])


def eval_checklist_rows(state: RunState) -> list[dict[str, Any]]:
    suite = evaluate_state("current_ui_run", state)
    return clean_rows(
        [
            {
                "Check": format_label(result.name),
                "Result": "Pass" if result.passed else "Fail",
                "Gate Score": f"{result.score:.2f}",
                "Details": compact_text(result.details),
            }
            for result in suite.results
        ]
    )


def clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    keys = list(rows[0].keys())
    keep = [
        key
        for key in keys
        if any(value not in (None, "") for value in (row.get(key) for row in rows))
    ]
    return [{key: row.get(key) for key in keep} for row in rows]


def format_label(value: str) -> str:
    return value.replace("_", " ").title()


def format_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    day = value.day
    return f"{day}{_ordinal_suffix(day)} {value.strftime('%B %Y')}"


def format_short_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    day = value.day
    return f"{day}{_ordinal_suffix(day)} {value.strftime('%B')}"


def format_money_millions(value: float | None) -> str:
    if value is None:
        return ""
    return format_money(value)


def format_money(value: float | None) -> str:
    if value is None:
        return ""
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{sign}${absolute / 1_000_000_000:,.1f}B"
    if absolute >= 1_000_000:
        return f"{sign}${absolute / 1_000_000:,.1f}M"
    if absolute >= 1_000:
        return f"{sign}${absolute / 1_000:,.1f}K"
    return f"{sign}${absolute:,.0f}"


def format_eps(value: float | None) -> str:
    if value is None:
        return ""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}%"


def format_seconds(duration_ms: float | None) -> str:
    if duration_ms is None:
        return ""
    return f"{duration_ms / 1000:,.2f}s"


def format_decimal(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def compact_text(value: str, *, limit: int = TEXT_LIMIT) -> str:
    if not value:
        return ""
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _warning_issue(code: str) -> str:
    if code.startswith("tool.alpha_vantage"):
        return "Optional Data Source Skipped"
    if code == "news.capped":
        return "News Limit Applied"
    if code.startswith("llm."):
        return "Agent Output Issue"
    if code.startswith("mem0."):
        return "Memory Lookup Issue"
    return format_label(code.split(".")[-1])


def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
