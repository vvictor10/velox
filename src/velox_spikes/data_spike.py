"""Run measured data-provider spikes using production adapters."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from time import sleep
from typing import Any

from velox.config import load_settings
from velox.models.company import CompanyIdentity
from velox.models.tool_result import ToolResult
from velox.paths import DATA_SPIKE_RESULTS_PATH
from velox.providers.alpha_vantage import AlphaVantageClient
from velox.providers.finnhub import FinnhubClient
from velox.providers.sec import SecClient
from velox.providers.ticker_lookup import load_ticker_cache, search_tickers


def run_data_spike(tickers: Iterable[str]) -> list[dict[str, Any]]:
    settings = load_settings()
    alpha_vantage = AlphaVantageClient(settings)
    finnhub = FinnhubClient(settings)
    sec = SecClient(settings)
    cache = load_ticker_cache()
    results: list[dict[str, Any]] = []

    for ticker in tickers:
        company = _resolve_company(ticker, cache.companies)
        if company is None:
            results.append({"ticker": ticker, "resolved": False, "tool_results": []})
            continue

        tool_results = []
        for call in (
            alpha_vantage.earnings_calendar,
            alpha_vantage.earnings_history,
            alpha_vantage.earnings_estimates,
            alpha_vantage.news_sentiment,
            alpha_vantage.company_overview,
        ):
            tool_results.append(call(company.ticker))
            sleep(1.1)
        tool_results.extend(
            [
                sec.submissions(company),
                sec.company_facts(company),
                finnhub.earnings_calendar(company.ticker),
                finnhub.earnings_surprises(company.ticker),
                finnhub.company_news(company.ticker),
            ]
        )
        results.append(
            {
                "ticker": company.ticker,
                "company_name": company.company_name,
                "exchange": company.exchange,
                "cik": company.cik,
                "resolved": True,
                "tool_results": [_summarize_tool_result(result) for result in tool_results],
            }
        )

    return results


def write_data_spike_report(results: list[dict[str, Any]]) -> None:
    DATA_SPIKE_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(UTC).isoformat()
    lines = [
        "# Data Spike Results",
        "",
        f"Captured at: `{captured_at}`",
        "",
        "This local note records source availability, response shapes, latency, and failure behavior.",
        "",
    ]
    for result in results:
        lines.extend(_format_ticker_result(result))
    DATA_SPIKE_RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def search_preview(query: str) -> list[CompanyIdentity]:
    return search_tickers(query, limit=10)


def _resolve_company(ticker: str, companies: list[CompanyIdentity]) -> CompanyIdentity | None:
    normalized = ticker.strip().upper()
    for company in companies:
        if company.ticker == normalized:
            return company
    return None


def _summarize_tool_result(result: ToolResult) -> dict[str, Any]:
    data = result.data
    return {
        "tool_name": result.tool_name,
        "status": result.status,
        "failure_category": result.failure_category,
        "duration_ms": result.duration_ms,
        "freshness": result.freshness,
        "fallback_used": result.fallback_used,
        "error": result.error,
        "shape": _shape(data),
    }


def _shape(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return {
            "type": "dict",
            "keys": list(data.keys())[:20],
            "record_counts": {
                key: len(value)
                for key, value in data.items()
                if isinstance(value, list)
            },
        }
    if isinstance(data, list):
        return {"type": "list", "count": len(data), "first_keys": _first_keys(data)}
    if data is None:
        return {"type": "none"}
    return {"type": type(data).__name__}


def _first_keys(data: list[Any]) -> list[str]:
    if not data or not isinstance(data[0], dict):
        return []
    return list(data[0].keys())[:20]


def _format_ticker_result(result: dict[str, Any]) -> list[str]:
    if not result["resolved"]:
        return [f"## {result['ticker']}", "", "Ticker was not found in local cache.", ""]
    lines = [
        f"## {result['ticker']} - {result['company_name']}",
        "",
        f"- Exchange: `{result['exchange']}`",
        f"- CIK: `{result['cik']}`",
        "",
        "| Tool | Status | Failure Category | Duration ms | Shape | Error |",
        "|---|---|---|---:|---|---|",
    ]
    for tool in result["tool_results"]:
        lines.append(
            "| {tool_name} | {status} | {failure_category} | {duration_ms} | {shape} | {error} |".format(
                tool_name=tool["tool_name"],
                status=tool["status"],
                failure_category=tool["failure_category"],
                duration_ms=tool["duration_ms"],
                shape=_compact(tool["shape"]),
                error=_compact(tool["error"]),
            )
        )
    lines.append("")
    return lines


def _compact(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    return text[:180] + "..." if len(text) > 180 else text
