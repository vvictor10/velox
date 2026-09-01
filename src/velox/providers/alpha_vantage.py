"""Alpha Vantage public market-data adapter."""

from __future__ import annotations

from time import monotonic, sleep

from velox.config import AppSettings
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.providers.http import get_csv_tool_result, get_json_tool_result

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._last_live_call_at: float | None = None

    def earnings_calendar(self, ticker: str, horizon: str = "3month") -> ToolResult:
        return self._query_csv(
            tool_name="alpha_vantage.earnings_calendar",
            function="EARNINGS_CALENDAR",
            symbol=ticker,
            horizon=horizon,
        )

    def earnings_history(self, ticker: str) -> ToolResult:
        return self._query(
            tool_name="alpha_vantage.earnings",
            function="EARNINGS",
            symbol=ticker,
        )

    def earnings_estimates(self, ticker: str) -> ToolResult:
        return self._query(
            tool_name="alpha_vantage.earnings_estimates",
            function="EARNINGS_ESTIMATES",
            symbol=ticker,
        )

    def news_sentiment(self, ticker: str, limit: int = 50) -> ToolResult:
        return self._query(
            tool_name="alpha_vantage.news_sentiment",
            function="NEWS_SENTIMENT",
            tickers=ticker,
            sort="LATEST",
            limit=str(limit),
        )

    def company_overview(self, ticker: str) -> ToolResult:
        return self._query(
            tool_name="alpha_vantage.company_overview",
            function="OVERVIEW",
            symbol=ticker,
        )

    def quote(self, ticker: str) -> ToolResult:
        return self._query(
            tool_name="alpha_vantage.quote",
            function="GLOBAL_QUOTE",
            symbol=ticker,
        )

    def _query(self, *, tool_name: str, function: str, **params: str) -> ToolResult:
        disabled = self._disabled_result(tool_name, function)
        if disabled is not None:
            return disabled
        if not self.settings.alpha_vantage_api_key:
            return ToolResult.failure(
                tool_name=tool_name,
                source=BASE_URL,
                started_at=date_started(),
                error="ALPHA_VANTAGE_API_KEY is not configured.",
                failure_category=FailureCategory.NON_RECOVERABLE,
            )
        self._pace_live_request()
        return get_json_tool_result(
            tool_name=tool_name,
            source=f"Alpha Vantage {function}",
            url=BASE_URL,
            params={
                "function": function,
                "apikey": self.settings.alpha_vantage_api_key.get_secret_value(),
                **params,
            },
            timeout_seconds=self.settings.node_timeout_seconds,
        )

    def _query_csv(self, *, tool_name: str, function: str, **params: str) -> ToolResult:
        disabled = self._disabled_result(tool_name, function)
        if disabled is not None:
            return disabled
        if not self.settings.alpha_vantage_api_key:
            return ToolResult.failure(
                tool_name=tool_name,
                source=BASE_URL,
                started_at=date_started(),
                error="ALPHA_VANTAGE_API_KEY is not configured.",
                failure_category=FailureCategory.NON_RECOVERABLE,
            )
        self._pace_live_request()
        return get_csv_tool_result(
            tool_name=tool_name,
            source=f"Alpha Vantage {function}",
            url=BASE_URL,
            params={
                "function": function,
                "apikey": self.settings.alpha_vantage_api_key.get_secret_value(),
                **params,
            },
            timeout_seconds=self.settings.node_timeout_seconds,
        )

    def _disabled_result(self, tool_name: str, function: str) -> ToolResult | None:
        if self.settings.alpha_vantage_live_enabled:
            return None
        return ToolResult.failure(
            tool_name=tool_name,
            source=f"Alpha Vantage {function}",
            started_at=date_started(),
            error=(
                "Alpha Vantage live calls are disabled by ALPHA_VANTAGE_LIVE_ENABLED=false "
                "to preserve the free daily request budget."
            ),
            failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            status=ToolStatus.SKIPPED,
        )

    def _pace_live_request(self) -> None:
        min_interval = self.settings.alpha_vantage_min_seconds_between_calls
        if min_interval <= 0:
            return
        now = monotonic()
        if self._last_live_call_at is not None:
            wait_seconds = min_interval - (now - self._last_live_call_at)
            if wait_seconds > 0:
                sleep(wait_seconds)
                now += wait_seconds
        self._last_live_call_at = now


def date_started():
    from datetime import UTC, datetime

    return datetime.now(UTC)
