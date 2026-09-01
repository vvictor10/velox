from __future__ import annotations

from datetime import UTC, datetime

from velox.config import AppSettings
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import Freshness, ToolResult
from velox.providers.alpha_vantage import AlphaVantageClient
from velox.providers.finnhub import FinnhubClient
from velox.providers.ticker_lookup import normalize_sec_ticker_payload, search_tickers


def test_normalize_sec_ticker_payload_and_search() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [789019, "Microsoft Corp", "MSFT", "Nasdaq"],
            [123, "Tiny OTC Company", "TINY", "OTC"],
        ],
    }
    cache = normalize_sec_ticker_payload(payload, source_url="https://example.test/tickers.json")

    assert cache.metadata.record_count == 3
    assert search_tickers("app", cache=cache)[0].ticker == "AAPL"
    assert search_tickers("microsoft", cache=cache)[0].ticker == "MSFT"
    assert search_tickers("tiny", cache=cache) == []
    assert search_tickers("tiny", cache=cache, major_exchanges_only=False)[0].ticker == "TINY"


def test_search_tickers_ranks_ticker_prefix_before_company_substring() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1, "Some Good Company", "AAA", "NYSE"],
            [2, "Alphabet Inc.", "GOOGL", "Nasdaq"],
            [3, "Alphabet Inc.", "GOOG", "Nasdaq"],
        ],
    }
    cache = normalize_sec_ticker_payload(payload, source_url="https://example.test/tickers.json")

    assert [company.ticker for company in search_tickers("goo", cache=cache, limit=3)] == [
        "GOOG",
        "GOOGL",
        "AAA",
    ]


def test_alpha_vantage_missing_key_is_non_recoverable() -> None:
    result = AlphaVantageClient(AppSettings(alpha_vantage_live_enabled=True)).earnings_history("AAPL")

    assert result.status == "failed"
    assert result.failure_category == FailureCategory.NON_RECOVERABLE
    assert "ALPHA_VANTAGE_API_KEY" in (result.error or "")


def test_alpha_vantage_live_disabled_is_visible_skip() -> None:
    result = AlphaVantageClient(AppSettings()).earnings_history("AAPL")

    assert result.status == "skipped"
    assert result.failure_category == FailureCategory.DEGRADED_CONTINUABLE
    assert "ALPHA_VANTAGE_LIVE_ENABLED=false" in (result.error or "")


def test_alpha_vantage_live_calls_are_throttled(monkeypatch) -> None:
    sleep_calls: list[float] = []
    clock = iter([100.0, 100.25])

    def fake_json_tool_result(**kwargs):
        return ToolResult.success(
            tool_name=kwargs["tool_name"],
            source=kwargs["source"],
            started_at=datetime.now(UTC),
            data={},
            freshness=Freshness.CURRENT,
        )

    monkeypatch.setattr("velox.providers.alpha_vantage.monotonic", lambda: next(clock))
    monkeypatch.setattr("velox.providers.alpha_vantage.sleep", sleep_calls.append)
    monkeypatch.setattr("velox.providers.alpha_vantage.get_json_tool_result", fake_json_tool_result)

    client = AlphaVantageClient(
        AppSettings(
            alpha_vantage_api_key="alpha-test",
            alpha_vantage_live_enabled=True,
            alpha_vantage_min_seconds_between_calls=1.25,
        )
    )

    client.earnings_history("AAPL")
    client.earnings_estimates("AAPL")

    assert sleep_calls == [1.0]


def test_finnhub_missing_key_is_degraded_continuable() -> None:
    result = FinnhubClient(AppSettings()).company_news("AAPL")

    assert result.status == "failed"
    assert result.failure_category == FailureCategory.DEGRADED_CONTINUABLE
    assert "FINNHUB_API_KEY" in (result.error or "")
