"""Normalize provider payloads into Velox evidence models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from velox.models.earnings import (
    AnnouncementTiming,
    EarningsEvent,
    EarningsSnapshot,
    HistoricalEarningsQuarter,
)
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.news import NewsItem, NewsSnapshot
from velox.models.tool_result import ToolResult, ToolStatus
from velox.models.warnings import WarningRecord, WarningSeverity


def build_evidence_pack(tool_results: list[ToolResult]) -> EvidencePack:
    records: list[EvidenceRecord] = []
    warnings: list[WarningRecord] = []

    for result in tool_results:
        if result.status == ToolStatus.SUCCESS or result.status == ToolStatus.FALLBACK_USED:
            record = _evidence_from_tool_result(result)
            if record is not None:
                records.append(record)
        elif result.error:
            warnings.append(
                WarningRecord(
                    code=f"tool.{result.tool_name}.{result.status}",
                    message=result.error,
                    source=result.tool_name,
                    failure_category=result.failure_category,
                    severity=WarningSeverity.WARNING,
                )
            )

    return EvidencePack(records=records, warnings=warnings).assign_ids()


def normalize_earnings_snapshot(ticker: str, evidence_pack: EvidencePack) -> EarningsSnapshot:
    next_event: EarningsEvent | None = None
    history: list[HistoricalEarningsQuarter] = []
    warnings: list[WarningRecord] = []

    for record in evidence_pack.records:
        if record.evidence_type != EvidenceType.EARNINGS:
            continue
        payload = record.payload
        if record.provider == "Alpha Vantage EARNINGS_CALENDAR":
            rows = payload.get("rows", [])
            if isinstance(rows, list) and rows:
                next_event = _alpha_calendar_event(rows[0], record.evidence_id)
            elif isinstance(rows, list):
                warnings.append(
                    WarningRecord(
                        code="earnings.calendar.empty",
                        message="Alpha Vantage returned no upcoming earnings calendar rows.",
                        source=record.provider,
                    )
                )
        elif record.provider == "Finnhub /calendar/earnings":
            events = payload.get("earningsCalendar", [])
            if isinstance(events, list) and events and next_event is None:
                next_event = _finnhub_calendar_event(events[0], record.evidence_id)
        elif record.provider == "Finnhub /stock/earnings":
            items = payload.get("items", [])
            if isinstance(items, list):
                history.extend(_finnhub_surprises(items, record.evidence_id))
        elif record.provider == "Alpha Vantage EARNINGS":
            quarters = payload.get("quarterlyEarnings", [])
            if isinstance(quarters, list):
                history.extend(_alpha_earnings_history(quarters[:8], record.evidence_id))

    if next_event is None:
        warnings.append(
            WarningRecord(
                code="earnings.forward_calendar.missing",
                message="No forward earnings calendar event was available from configured providers.",
            )
        )
    if not history:
        warnings.append(
            WarningRecord(
                code="earnings.history.missing",
                message="No recent historical earnings records were available from configured providers.",
            )
        )

    return EarningsSnapshot(ticker=ticker, next_event=next_event, history=history, warnings=warnings)


def normalize_news_snapshot(ticker: str, evidence_pack: EvidencePack, limit: int = 25) -> NewsSnapshot:
    items: list[NewsItem] = []
    warnings: list[WarningRecord] = []
    seen_urls: set[str] = set()

    for record in evidence_pack.records:
        if record.evidence_type != EvidenceType.NEWS:
            continue
        payload = record.payload
        if record.provider == "Alpha Vantage NEWS_SENTIMENT":
            feed = payload.get("feed", [])
            if isinstance(feed, list):
                for item in feed:
                    parsed = _alpha_news_item(item, record.evidence_id)
                    if parsed and _add_if_new(parsed, items, seen_urls, limit):
                        continue
        elif record.provider == "Finnhub /company-news":
            payload_items = payload.get("items", [])
            if isinstance(payload_items, list):
                for item in payload_items:
                    parsed = _finnhub_news_item(item, record.evidence_id)
                    if parsed and _add_if_new(parsed, items, seen_urls, limit):
                        continue

    items.sort(key=lambda item: item.published_at, reverse=True)
    if not items:
        warnings.append(
            WarningRecord(
                code="news.missing",
                message="No recent news was available from configured providers.",
            )
        )
    elif len(items) == limit:
        warnings.append(
            WarningRecord(
                code="news.capped",
                message=f"News was capped at {limit} deduplicated items for cost and context control.",
                severity=WarningSeverity.INFO,
            )
        )

    return NewsSnapshot(ticker=ticker, items=items, warnings=warnings)


def _evidence_from_tool_result(result: ToolResult) -> EvidenceRecord | None:
    if result.data is None:
        return None
    provider = result.source
    if "EARNINGS" in result.source or "/calendar/earnings" in result.source or "/stock/earnings" in result.source:
        evidence_type = EvidenceType.EARNINGS
    elif "NEWS" in result.source or "/company-news" in result.source:
        evidence_type = EvidenceType.NEWS
    elif "SEC EDGAR submissions" in result.source:
        evidence_type = EvidenceType.SEC_FILING
    elif "SEC EDGAR company facts" in result.source:
        evidence_type = EvidenceType.COMPANY_FACT
    else:
        evidence_type = EvidenceType.COMPANY_CONTEXT
    return EvidenceRecord(
        evidence_type=evidence_type,
        provider=provider,
        title=result.tool_name,
        captured_at=result.ended_at or datetime.now(UTC),
        freshness=result.freshness,
        payload=result.data if isinstance(result.data, dict) else {"items": result.data},
    )


def _alpha_calendar_event(row: dict[str, Any], evidence_id: str | None) -> EarningsEvent:
    return EarningsEvent(
        report_date=_parse_date(row.get("reportDate") or row.get("reportDate".lower())),
        fiscal_quarter=_parse_int(row.get("fiscalQuarterEnding")),
        fiscal_year=_parse_int(row.get("fiscalYear")),
        eps_estimate=_parse_float(row.get("estimate")),
        source_provider="Alpha Vantage",
        source_evidence_id=evidence_id,
    )


def _finnhub_calendar_event(row: dict[str, Any], evidence_id: str | None) -> EarningsEvent:
    return EarningsEvent(
        report_date=_parse_date(row.get("date")),
        timing=_parse_finnhub_timing(row.get("hour")),
        fiscal_quarter=_parse_int(row.get("quarter")),
        fiscal_year=_parse_int(row.get("year")),
        eps_estimate=_parse_float(row.get("epsEstimate")),
        revenue_estimate=_parse_float(row.get("revenueEstimate")),
        source_provider="Finnhub",
        source_evidence_id=evidence_id,
    )


def _finnhub_surprises(rows: list[dict[str, Any]], evidence_id: str | None) -> list[HistoricalEarningsQuarter]:
    return [
        HistoricalEarningsQuarter(
            period=_parse_date(row.get("period")),
            fiscal_quarter=_parse_int(row.get("quarter")),
            fiscal_year=_parse_int(row.get("year")),
            eps_actual=_parse_float(row.get("actual")),
            eps_estimate=_parse_float(row.get("estimate")),
            surprise=_parse_float(row.get("surprise")),
            surprise_percent=_parse_float(row.get("surprisePercent")),
            source_provider="Finnhub",
            source_evidence_id=evidence_id,
        )
        for row in rows[:8]
        if isinstance(row, dict)
    ]


def _alpha_earnings_history(rows: list[dict[str, Any]], evidence_id: str | None) -> list[HistoricalEarningsQuarter]:
    return [
        HistoricalEarningsQuarter(
            period=_parse_date(row.get("fiscalDateEnding") or row.get("reportedDate")),
            eps_actual=_parse_float(row.get("reportedEPS")),
            eps_estimate=_parse_float(row.get("estimatedEPS")),
            surprise=_parse_float(row.get("surprise")),
            surprise_percent=_parse_float(row.get("surprisePercentage")),
            source_provider="Alpha Vantage",
            source_evidence_id=evidence_id,
        )
        for row in rows
        if isinstance(row, dict)
    ]


def _alpha_news_item(row: dict[str, Any], evidence_id: str | None) -> NewsItem | None:
    published = _parse_alpha_news_time(row.get("time_published"))
    headline = row.get("title")
    source = row.get("source")
    if not published or not headline or not source:
        return None
    ticker_sentiment = row.get("ticker_sentiment", [])
    related = [
        item.get("ticker")
        for item in ticker_sentiment
        if isinstance(item, dict) and isinstance(item.get("ticker"), str)
    ]
    return NewsItem(
        headline=str(headline),
        source=str(source),
        published_at=published,
        url=_as_str(row.get("url")),
        summary=_as_str(row.get("summary")),
        related_tickers=related,
        provider_sentiment={
            "overall_sentiment_score": row.get("overall_sentiment_score"),
            "overall_sentiment_label": row.get("overall_sentiment_label"),
        },
        source_provider="Alpha Vantage",
        source_evidence_id=evidence_id,
    )


def _finnhub_news_item(row: dict[str, Any], evidence_id: str | None) -> NewsItem | None:
    published = row.get("datetime")
    headline = row.get("headline")
    source = row.get("source")
    if not isinstance(published, int) or not headline or not source:
        return None
    related = _as_str(row.get("related"))
    return NewsItem(
        headline=str(headline),
        source=str(source),
        published_at=datetime.fromtimestamp(published, UTC),
        url=_as_str(row.get("url")),
        summary=_as_str(row.get("summary")),
        related_tickers=[ticker.strip() for ticker in related.split(",") if ticker.strip()]
        if related
        else [],
        source_provider="Finnhub",
        source_evidence_id=evidence_id,
    )


def _add_if_new(item: NewsItem, items: list[NewsItem], seen_urls: set[str], limit: int) -> bool:
    key = item.url or f"{item.source}:{item.headline}"
    if key in seen_urls or len(items) >= limit:
        return False
    seen_urls.add(key)
    items.append(item)
    return True


def _parse_finnhub_timing(value: Any) -> AnnouncementTiming:
    mapping = {
        "bmo": AnnouncementTiming.BEFORE_MARKET_OPEN,
        "amc": AnnouncementTiming.AFTER_MARKET_CLOSE,
        "dmh": AnnouncementTiming.DURING_MARKET_HOURS,
    }
    return mapping.get(str(value).lower(), AnnouncementTiming.UNKNOWN)


def _parse_alpha_news_time(value: Any) -> datetime | None:
    text = _as_str(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_date(value: Any):
    text = _as_str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value in {None, "", "None", "none"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value in {None, "", "None", "none"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
