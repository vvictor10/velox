from __future__ import annotations

from datetime import UTC, datetime

from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult
from velox.providers.normalization import (
    build_evidence_pack,
    normalize_earnings_snapshot,
    normalize_news_snapshot,
)


def test_build_evidence_pack_and_normalize_finnhub_fallbacks() -> None:
    started_at = datetime.now(UTC)
    tool_results = [
        ToolResult.success(
            tool_name="finnhub.earnings_calendar",
            source="Finnhub /calendar/earnings",
            started_at=started_at,
            data={
                "earningsCalendar": [
                    {
                        "date": "2026-10-29",
                        "hour": "amc",
                        "quarter": 4,
                        "year": 2026,
                        "epsEstimate": 1.5,
                        "revenueEstimate": 100000000000,
                    }
                ]
            },
        ),
        ToolResult.success(
            tool_name="finnhub.earnings_surprises",
            source="Finnhub /stock/earnings",
            started_at=started_at,
            data=[
                {
                    "actual": 1.4,
                    "estimate": 1.35,
                    "period": "2026-06-30",
                    "quarter": 3,
                    "surprise": 0.05,
                    "surprisePercent": 3.7,
                    "year": 2026,
                }
            ],
        ),
        ToolResult.success(
            tool_name="finnhub.company_news",
            source="Finnhub /company-news",
            started_at=started_at,
            data=[
                {
                    "datetime": 1793232000,
                    "headline": "Company shares earnings date",
                    "source": "Example News",
                    "summary": "The company set its earnings date.",
                    "url": "https://example.test/news",
                    "related": "AAPL,MSFT",
                }
            ],
        ),
    ]

    pack = build_evidence_pack(tool_results)
    earnings = normalize_earnings_snapshot("AAPL", pack)
    news = normalize_news_snapshot("AAPL", pack)

    assert pack.citation_ids == {"E1", "E2", "E3"}
    assert earnings.next_event and earnings.next_event.source_provider == "Finnhub"
    assert earnings.next_event.revenue_estimate == 100000000000
    assert earnings.history[0].surprise_percent == 3.7
    assert news.items[0].headline == "Company shares earnings date"
    assert news.items[0].related_tickers == ["AAPL", "MSFT"]


def test_normalize_alpha_payloads_and_capped_news_warning() -> None:
    started_at = datetime.now(UTC)
    tool_results = [
        ToolResult.success(
            tool_name="alpha_vantage.earnings_calendar",
            source="Alpha Vantage EARNINGS_CALENDAR",
            started_at=started_at,
            data={
                "rows": [
                    {
                        "reportDate": "2026-10-29",
                        "fiscalDateEnding": "2026-09-30",
                        "estimate": "1.50",
                    }
                ],
                "row_count": 1,
            },
        ),
        ToolResult.success(
            tool_name="alpha_vantage.earnings",
            source="Alpha Vantage EARNINGS",
            started_at=started_at,
            data={
                "quarterlyEarnings": [
                    {
                        "fiscalDateEnding": "2026-06-30",
                        "reportedEPS": "1.40",
                        "estimatedEPS": "1.35",
                        "surprise": "0.05",
                        "surprisePercentage": "3.7",
                    }
                ]
            },
        ),
        ToolResult.success(
            tool_name="alpha_vantage.news_sentiment",
            source="Alpha Vantage NEWS_SENTIMENT",
            started_at=started_at,
            data={
                "feed": [
                    {
                        "time_published": "20261029T120000",
                        "title": "Company updates investors",
                        "source": "Example Wire",
                        "summary": "A public update.",
                        "url": "https://example.test/alpha-news",
                        "overall_sentiment_score": "0.2",
                        "overall_sentiment_label": "Neutral",
                        "ticker_sentiment": [{"ticker": "AAPL"}],
                    }
                ]
            },
        ),
    ]

    pack = build_evidence_pack(tool_results)
    earnings = normalize_earnings_snapshot("AAPL", pack)
    news = normalize_news_snapshot("AAPL", pack, limit=1)

    assert earnings.next_event and earnings.next_event.eps_estimate == 1.5
    assert earnings.history[0].eps_actual == 1.4
    assert news.items[0].provider_sentiment["overall_sentiment_label"] == "Neutral"
    assert news.warnings[0].code == "news.capped"


def test_failed_tool_results_become_evidence_pack_warnings() -> None:
    started_at = datetime.now(UTC)
    pack = build_evidence_pack(
        [
            ToolResult.failure(
                tool_name="alpha_vantage.news_sentiment",
                source="Alpha Vantage NEWS_SENTIMENT",
                started_at=started_at,
                error="Rate limited.",
                failure_category=FailureCategory.RECOVERABLE,
            )
        ]
    )

    assert pack.records == []
    assert pack.warnings[0].message == "Rate limited."
    assert pack.warnings[0].failure_category == FailureCategory.RECOVERABLE
