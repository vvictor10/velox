"""LangGraph state models for Velox workflow runs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from velox.models.company import CompanyIdentity
from velox.models.earnings import EarningsSnapshot
from velox.models.evidence import EvidencePack
from velox.models.failures import FallbackRecord, RetryRecord
from velox.models.news import NewsSnapshot
from velox.models.report import (
    ApprovalStatus,
    DeltaFinding,
    EarningsBrief,
    PriorReportMemory,
    ReviewerResult,
    RiskFinding,
)
from velox.models.telemetry import RunTelemetry
from velox.models.tool_result import ToolResult
from velox.models.warnings import WarningRecord


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    STOPPED = "stopped"


class RunState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: RunStatus = RunStatus.CREATED
    progress_text: str = "Ready."
    selected_ticker: str | None = None
    company: CompanyIdentity | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence_pack: EvidencePack = Field(default_factory=EvidencePack)
    earnings: EarningsSnapshot | None = None
    news: NewsSnapshot | None = None
    warnings: list[WarningRecord] = Field(default_factory=list)
    retry_records: list[RetryRecord] = Field(default_factory=list)
    fallback_records: list[FallbackRecord] = Field(default_factory=list)
    prior_memory: PriorReportMemory | None = None
    news_themes: list[dict[str, object]] = Field(default_factory=list)
    delta_findings: list[DeltaFinding] = Field(default_factory=list)
    risk_findings: list[RiskFinding] = Field(default_factory=list)
    brief: EarningsBrief | None = None
    reviewer_result: ReviewerResult | None = None
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUESTED
    telemetry: RunTelemetry | None = None
    idempotency_keys: dict[str, str] = Field(default_factory=dict)
    node_timeout_seconds: int = 45
    run_budget_seconds: int = 300

    def touch(self, *, progress_text: str | None = None, status: RunStatus | None = None) -> RunState:
        return self.model_copy(
            update={
                "updated_at": datetime.now(UTC),
                "progress_text": progress_text or self.progress_text,
                "status": status or self.status,
            }
        )

    def add_tool_result(self, result: ToolResult) -> RunState:
        warnings = list(self.warnings)
        if result.error:
            warnings.append(
                WarningRecord(
                    code=f"tool.{result.tool_name}.{result.status}",
                    message=result.error,
                    source=result.tool_name,
                    failure_category=result.failure_category,
                )
            )
        return self.model_copy(
            update={
                "updated_at": datetime.now(UTC),
                "tool_results": [*self.tool_results, result],
                "warnings": warnings,
            }
        )

    def completed_with_warnings(self) -> bool:
        return bool(self.warnings or self.evidence_pack.warnings)
