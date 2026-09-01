"""SEC EDGAR public API adapter."""

from __future__ import annotations

from velox.config import AppSettings
from velox.models.company import CompanyIdentity
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult, ToolStatus
from velox.providers.http import get_json_tool_result

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class SecClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def submissions(self, company: CompanyIdentity) -> ToolResult:
        return self._get(
            tool_name="sec.submissions",
            source="SEC EDGAR submissions",
            url=SUBMISSIONS_URL.format(cik=company.cik_padded),
        )

    def company_facts(self, company: CompanyIdentity) -> ToolResult:
        return self._get(
            tool_name="sec.company_facts",
            source="SEC EDGAR company facts",
            url=COMPANY_FACTS_URL.format(cik=company.cik_padded),
        )

    def _get(self, *, tool_name: str, source: str, url: str) -> ToolResult:
        if not self.settings.sec_live_enabled:
            from datetime import UTC, datetime

            return ToolResult.failure(
                tool_name=tool_name,
                source=source,
                started_at=datetime.now(UTC),
                error="SEC live calls are disabled by SEC_LIVE_ENABLED=false.",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                status=ToolStatus.SKIPPED,
            )
        if not self.settings.sec_user_agent:
            from datetime import UTC, datetime

            return ToolResult.failure(
                tool_name=tool_name,
                source=source,
                started_at=datetime.now(UTC),
                error="SEC_USER_AGENT is not configured.",
                failure_category=FailureCategory.NON_RECOVERABLE,
            )
        return get_json_tool_result(
            tool_name=tool_name,
            source=source,
            url=url,
            headers={
                "User-Agent": self.settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "data.sec.gov",
            },
            timeout_seconds=self.settings.node_timeout_seconds,
        )
