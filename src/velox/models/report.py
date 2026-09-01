"""Structured report, analysis, and reviewer models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from velox.models.warnings import WarningRecord


class ApprovalStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class PriorReportStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    FOUND = "found"
    MISSING = "missing"
    LOOKUP_FAILED = "lookup_failed"


class PriorReportMemory(BaseModel):
    ticker: str
    cik: str | None = None
    status: PriorReportStatus = PriorReportStatus.NOT_CHECKED
    memory_id: str | None = None
    report_timestamp: datetime | None = None
    summary: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    warnings: list[WarningRecord] = Field(default_factory=list)


class DeltaCategory(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    STALE = "stale"
    MISSING_PRIOR = "missing_prior"


class DeltaFinding(BaseModel):
    category: DeltaCategory
    finding: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class RiskFinding(BaseModel):
    risk: str
    severity: str
    rationale: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    watch_item: str | None = None


class ReportSection(BaseModel):
    title: str
    body: str
    citation_ids: list[str] = Field(default_factory=list)


class EarningsBrief(BaseModel):
    ticker: str
    company_name: str
    headline: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sections: list[ReportSection] = Field(default_factory=list)
    warnings: list[WarningRecord] = Field(default_factory=list)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    model_ids: dict[str, str] = Field(default_factory=dict)

    def all_citation_ids(self) -> list[str]:
        citation_ids: list[str] = []
        for section in self.sections:
            citation_ids.extend(section.citation_ids)
        return citation_ids


class ReviewerFinding(BaseModel):
    code: str
    message: str
    severity: str
    citation_ids: list[str] = Field(default_factory=list)
    requires_revision: bool = False


class ReviewerResult(BaseModel):
    passed: bool
    findings: list[ReviewerFinding] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)

    @property
    def requires_revision(self) -> bool:
        return any(finding.requires_revision for finding in self.findings)
