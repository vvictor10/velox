"""Mem0-backed approved report memory with local snapshot mirror."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from mem0 import MemoryClient
from mem0.client.types import AddMemoryOptions, SearchMemoryOptions, UpdateMemoryOptions
from mem0.exceptions import (
    AuthenticationError,
    ConfigurationError,
    MemoryError,
    MemoryNotFoundError,
    MemoryQuotaExceededError,
    NetworkError,
    RateLimitError,
    ValidationError,
)
from pydantic import BaseModel, Field

from velox.config import AppSettings
from velox.models.company import CompanyIdentity
from velox.models.report import EarningsBrief, PriorReportMemory, PriorReportStatus
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import Freshness, ToolResult, ToolStatus
from velox.models.warnings import WarningRecord
from velox.paths import BRIEFS_DIR

VELOX_MEMORY_USER_ID = "velox-public-demo"
VELOX_MEMORY_AGENT_ID = "velox"
MAX_SAVED_COMPANIES = 10
MEM0_HANDLED_EXCEPTIONS = (
    AuthenticationError,
    ConfigurationError,
    MemoryError,
    MemoryNotFoundError,
    MemoryQuotaExceededError,
    NetworkError,
    RateLimitError,
    ValidationError,
    RuntimeError,
    ValueError,
)
MEM0_MISS_EXCEPTIONS = (MemoryNotFoundError,)
SNAPSHOT_MARKER = "VELOX_APPROVED_BRIEF_SNAPSHOT_JSON:"


class MemoryClientProtocol(Protocol):
    def get(self, memory_id: str) -> dict[str, Any]: ...

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]: ...

    def add(self, messages: Any, **kwargs: Any) -> dict[str, Any]: ...

    def update(self, memory_id: str, **kwargs: Any) -> dict[str, Any]: ...


class MemorySaveResult(BaseModel):
    memory: PriorReportMemory
    tool_result: ToolResult
    saved_snapshot_path: Path | None = None


class MemoryLimitStatus(BaseModel):
    saved_count: int
    max_saved: int = MAX_SAVED_COMPANIES
    at_limit: bool = False
    tickers: list[str] = Field(default_factory=list)


class Mem0ReportStore:
    def __init__(
        self,
        settings: AppSettings,
        *,
        client: MemoryClientProtocol | None = None,
        snapshot_dir: Path = BRIEFS_DIR,
    ) -> None:
        self.settings = settings
        self.client = client
        self.snapshot_dir = snapshot_dir

    def lookup_prior_report(self, company: CompanyIdentity) -> tuple[PriorReportMemory, ToolResult]:
        started_at = datetime.now(UTC)
        local_memory = self._load_local_snapshot(company)
        if not self.settings.mem0_api_key and self.client is None:
            memory = local_memory or PriorReportMemory(
                ticker=company.ticker,
                cik=company.cik,
                status=PriorReportStatus.MISSING,
            )
            return memory, ToolResult.failure(
                tool_name="mem0.lookup_prior_report",
                source="Mem0",
                started_at=started_at,
                status=ToolStatus.SKIPPED,
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                freshness=Freshness.NOT_APPLICABLE,
                error="MEM0_API_KEY is not configured; using local snapshot mirror only.",
                data=memory.model_dump(mode="json"),
            )

        try:
            memory, response, strategy = self._lookup_remote_memory(company, local_memory)
            if memory is None:
                memory = PriorReportMemory(
                    ticker=company.ticker,
                    cik=company.cik,
                    status=PriorReportStatus.MISSING,
                )
            return memory, ToolResult.success(
                tool_name="mem0.lookup_prior_report",
                source=f"Mem0 {strategy}",
                started_at=started_at,
                data=response,
                freshness=Freshness.CURRENT,
            )
        except MEM0_HANDLED_EXCEPTIONS as exc:
            warning = WarningRecord(
                code="mem0.lookup_failed",
                message="Mem0 prior-report lookup failed; continuing without claiming no prior report exists.",
                source="Mem0",
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
            )
            memory = local_memory or PriorReportMemory(
                ticker=company.ticker,
                cik=company.cik,
                status=PriorReportStatus.LOOKUP_FAILED,
                warnings=[warning],
            )
            if local_memory is not None:
                memory = local_memory.model_copy(
                    update={"status": PriorReportStatus.LOOKUP_FAILED, "warnings": [warning]}
                )
            return memory, ToolResult.failure(
                tool_name="mem0.lookup_prior_report",
                source="Mem0",
                started_at=started_at,
                status=ToolStatus.LOOKUP_FAILED,
                failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                freshness=Freshness.UNKNOWN,
                error=f"Mem0 lookup failed: {exc}",
                data=memory.model_dump(mode="json"),
            )

    def _lookup_remote_memory(
        self,
        company: CompanyIdentity,
        local_memory: PriorReportMemory | None,
    ) -> tuple[PriorReportMemory | None, dict[str, Any], str]:
        client = self._client()
        attempts: list[dict[str, Any]] = []
        if local_memory and local_memory.memory_id:
            try:
                response = client.get(local_memory.memory_id)
                memory = _memory_from_record(company, response)
                if memory is not None:
                    return memory, {"strategy": "get_by_memory_id", "response": response}, "get_by_memory_id"
                attempts.append({"strategy": "get_by_memory_id", "status": "miss", "response": response})
            except MEM0_MISS_EXCEPTIONS as exc:
                attempts.append({"strategy": "get_by_memory_id", "status": "miss", "error": str(exc)})
            except MEM0_HANDLED_EXCEPTIONS as exc:
                attempts.append({"strategy": "get_by_memory_id", "status": "error", "error": str(exc)})

        try:
            search_response = client.search(
                query=f"latest approved Velox earnings brief for {company.ticker} {company.company_name}",
                options=SearchMemoryOptions(
                    filters=_filters(company),
                    top_k=1,
                    latest_only=True,
                ),
            )
            search_memory = _memory_from_search_response(company, search_response) or local_memory
            if search_memory is None:
                return (
                    None,
                    {"strategy": "not_found", "response": search_response, "attempts": attempts},
                    "not_found",
                )
            return (
                search_memory,
                {"strategy": "semantic_search", "response": search_response, "attempts": attempts},
                "semantic_search",
            )
        except MEM0_HANDLED_EXCEPTIONS as exc:
            attempts.append({"strategy": "semantic_search", "status": "error", "error": str(exc)})

        if any(attempt.get("status") == "miss" for attempt in attempts) and local_memory is None:
            return None, {"strategy": "all_remote_lookup_methods", "attempts": attempts}, "not_found"
        raise RuntimeError("Mem0 lookup failed across all lookup methods.")

    def save_approved_report(
        self,
        *,
        company: CompanyIdentity,
        brief: EarningsBrief,
        approved: bool,
        existing_memory_id: str | None = None,
    ) -> MemorySaveResult:
        started_at = datetime.now(UTC)
        if not approved:
            memory = PriorReportMemory(
                ticker=company.ticker,
                cik=company.cik,
                status=PriorReportStatus.NOT_CHECKED,
                summary="Save skipped because user approval was not provided.",
            )
            return MemorySaveResult(
                memory=memory,
                tool_result=ToolResult.failure(
                    tool_name="mem0.save_approved_report",
                    source="Mem0",
                    started_at=started_at,
                    status=ToolStatus.SKIPPED,
                    failure_category=FailureCategory.NON_RECOVERABLE,
                    freshness=Freshness.NOT_APPLICABLE,
                    error="User approval is required before saving report memory.",
                ),
            )

        limit_status = self.memory_limit_status()
        existing_tickers = set(limit_status.tickers)
        if limit_status.at_limit and company.ticker not in existing_tickers:
            memory = PriorReportMemory(
                ticker=company.ticker,
                cik=company.cik,
                status=PriorReportStatus.NOT_CHECKED,
                summary="Save blocked because the 10-company memory limit is reached.",
            )
            return MemorySaveResult(
                memory=memory,
                tool_result=ToolResult.failure(
                    tool_name="mem0.save_approved_report",
                    source="Mem0",
                    started_at=started_at,
                    status=ToolStatus.SKIPPED,
                    failure_category=FailureCategory.NON_RECOVERABLE,
                    freshness=Freshness.NOT_APPLICABLE,
                    error="Memory limit reached. Clear an older saved report before saving a new ticker.",
                    data=limit_status.model_dump(),
                ),
            )

        memory = _memory_from_brief(company, brief)
        snapshot_path = self._write_local_snapshot(memory)

        if not self.settings.mem0_api_key and self.client is None:
            return MemorySaveResult(
                memory=memory,
                saved_snapshot_path=snapshot_path,
                tool_result=ToolResult.failure(
                    tool_name="mem0.save_approved_report",
                    source="Mem0",
                    started_at=started_at,
                    status=ToolStatus.SKIPPED,
                    failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                    freshness=Freshness.CURRENT,
                    error="MEM0_API_KEY is not configured; saved local snapshot only.",
                    data=memory.model_dump(mode="json"),
                ),
            )

        try:
            client = self._client()
            metadata = _metadata(company, memory.report_timestamp)
            if existing_memory_id:
                response = client.update(
                    existing_memory_id,
                    options=UpdateMemoryOptions(
                        text=_memory_text(memory),
                        metadata=metadata,
                        timestamp=int((memory.report_timestamp or datetime.now(UTC)).timestamp()),
                    ),
                )
            else:
                response = client.add(
                    _memory_text(memory),
                    options=AddMemoryOptions(
                        filters=_filters(company),
                        metadata=metadata,
                        infer=False,
                        timestamp=int((memory.report_timestamp or datetime.now(UTC)).timestamp()),
                    ),
                    **_entity_ids(),
                )
            memory_id = existing_memory_id or _extract_memory_id(response)
            memory = memory.model_copy(
                update={
                    "memory_id": memory_id,
                    "payload": {**memory.payload, "mem0_response": response},
                }
            )
            snapshot_path = self._write_local_snapshot(memory)
            verified_memory, verification_response, verification_strategy = self._lookup_remote_memory(
                company,
                memory,
            )
            if verified_memory is None or (memory_id and verified_memory.memory_id != memory_id):
                return MemorySaveResult(
                    memory=memory,
                    saved_snapshot_path=snapshot_path,
                    tool_result=ToolResult.failure(
                        tool_name="mem0.save_approved_report",
                        source="Mem0",
                        started_at=started_at,
                        status=ToolStatus.FAILED,
                        failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                        freshness=Freshness.CURRENT,
                        error="Mem0 save completed but immediate lookup verification did not retrieve the saved report.",
                        data={
                            "save_response": response,
                            "verification": verification_response,
                        },
                    ),
                )
            return MemorySaveResult(
                memory=memory,
                saved_snapshot_path=snapshot_path,
                tool_result=ToolResult.success(
                    tool_name="mem0.save_approved_report",
                    source=f"Mem0 verified via {verification_strategy}",
                    started_at=started_at,
                    data={
                        "save_response": response,
                        "verification": verification_response,
                    },
                    freshness=Freshness.CURRENT,
                ),
            )
        except MEM0_HANDLED_EXCEPTIONS as exc:
            return MemorySaveResult(
                memory=memory,
                saved_snapshot_path=snapshot_path,
                tool_result=ToolResult.failure(
                    tool_name="mem0.save_approved_report",
                    source="Mem0",
                    started_at=started_at,
                    status=ToolStatus.FAILED,
                    failure_category=FailureCategory.DEGRADED_CONTINUABLE,
                    freshness=Freshness.CURRENT,
                    error=f"Mem0 save failed after local snapshot was written: {exc}",
                    data=memory.model_dump(mode="json"),
                ),
            )

    def memory_limit_status(self) -> MemoryLimitStatus:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshots = sorted(self.snapshot_dir.glob("*.json"))
        tickers = [path.stem.upper() for path in snapshots]
        return MemoryLimitStatus(
            saved_count=len(tickers),
            at_limit=len(tickers) >= MAX_SAVED_COMPANIES,
            tickers=tickers,
        )

    def _client(self) -> MemoryClientProtocol:
        if self.client is not None:
            return self.client
        if not self.settings.mem0_api_key:
            raise ValueError("MEM0_API_KEY is not configured.")
        self.client = MemoryClient(api_key=self.settings.mem0_api_key.get_secret_value())
        return self.client

    def _snapshot_path(self, company: CompanyIdentity) -> Path:
        return self.snapshot_dir / f"{company.ticker.upper()}.json"

    def _load_local_snapshot(self, company: CompanyIdentity) -> PriorReportMemory | None:
        path = self._snapshot_path(company)
        if not path.exists():
            return None
        return PriorReportMemory.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_local_snapshot(self, memory: PriorReportMemory) -> Path:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / f"{memory.ticker.upper()}.json"
        path.write_text(memory.model_dump_json(indent=2), encoding="utf-8")
        return path


def _filters(company: CompanyIdentity) -> dict[str, Any]:
    return {
        "user_id": VELOX_MEMORY_USER_ID,
        "agent_id": VELOX_MEMORY_AGENT_ID,
        "app_id": "velox",
        "metadata": {
            "ticker": company.ticker.upper(),
            "cik": company.cik,
            "memory_type": "approved_earnings_brief",
        },
    }


def _entity_ids() -> dict[str, str]:
    return {
        "user_id": VELOX_MEMORY_USER_ID,
        "agent_id": VELOX_MEMORY_AGENT_ID,
        "app_id": "velox",
    }


def _metadata(company: CompanyIdentity, report_timestamp: datetime | None) -> dict[str, Any]:
    return {
        "ticker": company.ticker.upper(),
        "cik": company.cik,
        "company_name": company.company_name,
        "memory_type": "approved_earnings_brief",
        "report_timestamp": (report_timestamp or datetime.now(UTC)).isoformat(),
    }


def _memory_from_brief(company: CompanyIdentity, brief: EarningsBrief) -> PriorReportMemory:
    summary = "\n".join(f"{section.title}: {section.body}" for section in brief.sections)
    return PriorReportMemory(
        ticker=company.ticker,
        cik=company.cik,
        status=PriorReportStatus.FOUND,
        report_timestamp=brief.generated_at,
        summary=summary[:4000],
        payload=brief.model_dump(mode="json"),
    )


def _memory_text(memory: PriorReportMemory) -> str:
    snapshot = _compact_memory_snapshot(memory)
    return (
        f"Velox approved earnings brief for {memory.ticker} "
        f"captured at {memory.report_timestamp}.\n\n"
        f"{memory.summary or ''}\n\n"
        f"{SNAPSHOT_MARKER}\n{json.dumps(snapshot, default=str, sort_keys=True)}"
    )


def _memory_from_search_response(company: CompanyIdentity, response: dict[str, Any] | list[Any]) -> PriorReportMemory | None:
    if isinstance(response, list):
        results = response
    else:
        results = response.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    return _memory_from_record(company, first)


def _memory_from_record(company: CompanyIdentity, record: Any) -> PriorReportMemory | None:
    if not isinstance(record, dict):
        return None
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    memory_text = record.get("memory") or record.get("text") or record.get("content")
    report_timestamp = _parse_datetime(metadata.get("report_timestamp"))
    summary = str(memory_text) if memory_text else None
    payload = _payload_from_memory_text(summary)
    return PriorReportMemory(
        ticker=company.ticker,
        cik=company.cik,
        status=PriorReportStatus.FOUND,
        memory_id=_as_str(record.get("id") or record.get("memory_id")),
        report_timestamp=report_timestamp,
        summary=summary,
        payload={**payload, "mem0_result": record},
    )


def _compact_memory_snapshot(memory: PriorReportMemory) -> dict[str, Any]:
    payload = memory.payload if isinstance(memory.payload, dict) else {}
    sections = payload.get("sections", [])
    warnings = payload.get("warnings", [])
    return {
        "ticker": memory.ticker,
        "cik": memory.cik,
        "report_timestamp": memory.report_timestamp.isoformat() if memory.report_timestamp else None,
        "headline": payload.get("headline"),
        "company_name": payload.get("company_name"),
        "sections": sections if isinstance(sections, list) else [],
        "warnings": warnings if isinstance(warnings, list) else [],
        "prompt_versions": payload.get("prompt_versions", {}),
        "model_ids": payload.get("model_ids", {}),
    }


def _payload_from_memory_text(memory_text: str | None) -> dict[str, Any]:
    if not memory_text or SNAPSHOT_MARKER not in memory_text:
        return {}
    _, raw_snapshot = memory_text.split(SNAPSHOT_MARKER, 1)
    try:
        snapshot = json.loads(raw_snapshot.strip())
    except json.JSONDecodeError:
        return {}
    return {"approved_brief_snapshot": snapshot} if isinstance(snapshot, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_memory_id(response: Any) -> str | None:
    if isinstance(response, dict):
        for key in ("id", "memory_id"):
            value = _as_str(response.get(key))
            if value:
                return value
        for key in ("memory", "result", "data"):
            value = _extract_memory_id(response.get(key))
            if value:
                return value
        results = response.get("results")
        if isinstance(results, list):
            for item in results:
                value = _extract_memory_id(item)
                if value:
                    return value
    if isinstance(response, list):
        for item in response:
            value = _extract_memory_id(item)
            if value:
                return value
    return None
