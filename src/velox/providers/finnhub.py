"""Finnhub fallback adapter for earnings and news."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from velox.config import AppSettings
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.providers.http import get_json_tool_result

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def company_news(self, ticker: str, days_back: int = 30) -> ToolResult:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=days_back)
        return self._get(
            tool_name="finnhub.company_news",
            endpoint="/company-news",
            params={"symbol": ticker, "from": start.isoformat(), "to": today.isoformat()},
        )

    def earnings_calendar(self, ticker: str) -> ToolResult:
        today = datetime.now(UTC).date()
        end = today + timedelta(days=90)
        return self._get(
            tool_name="finnhub.earnings_calendar",
            endpoint="/calendar/earnings",
            params={"symbol": ticker, "from": today.isoformat(), "to": end.isoformat()},
        )

    def earnings_surprises(self, ticker: str) -> ToolResult:
        return self._get(
            tool_name="finnhub.earnings_surprises",
            endpoint="/stock/earnings",
            params={"symbol": ticker},
        )

    def _get(self, *, tool_name: str, endpoint: str, params: dict[str, str]) -> ToolResult:
        if not self.settings.finnhub_live_enabled:
            return ToolResult.failure(
                tool_name=tool_name,
                source=f"Finnhub {endpoint}",
                started_at=_started_at(),
                error="Finnhub live calls are disabled by FINNHUB_LIVE_ENABLED=false.",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                status=ToolStatus.SKIPPED,
            )
        if not self.settings.finnhub_api_key:
            return ToolResult.failure(
                tool_name=tool_name,
                source=f"Finnhub {endpoint}",
                started_at=_started_at(),
                error="FINNHUB_API_KEY is not configured.",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            )
        return get_json_tool_result(
            tool_name=tool_name,
            source=f"Finnhub {endpoint}",
            url=f"{BASE_URL}{endpoint}",
            params={**params, "token": self.settings.finnhub_api_key.get_secret_value()},
            timeout_seconds=self.settings.node_timeout_seconds,
        )


def _started_at():
    return datetime.now(UTC)
