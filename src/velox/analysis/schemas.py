"""Structured LLM output schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DeltaCategory(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    STALE = "stale"
    MISSING_PRIOR = "missing_prior"


class NewsThemeItem(BaseModel):
    theme: str
    summary: str
    supporting_evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class NewsThemeOutput(BaseModel):
    themes: list[NewsThemeItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class DeltaFindingItem(BaseModel):
    category: DeltaCategory
    finding: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class DeltaOutput(BaseModel):
    findings: list[DeltaFindingItem] = Field(default_factory=list)
    prior_report_status: str
    missing_data_notes: list[str] = Field(default_factory=list)


class RiskItem(BaseModel):
    risk: str
    severity: Severity
    rationale: str
    supporting_evidence_ids: list[str] = Field(min_length=1)
    watch_item: str


class RiskOutput(BaseModel):
    risks: list[RiskItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class BriefSectionItem(BaseModel):
    title: str
    body: str
    citation_ids: list[str] = Field(default_factory=list)


class BriefOutput(BaseModel):
    headline: str
    sections: list[BriefSectionItem]
    warnings: list[str] = Field(default_factory=list)
    source_ids_used: list[str] = Field(default_factory=list)


class ReviewerFindingItem(BaseModel):
    code: str
    message: str
    severity: Severity
    citation_ids: list[str] = Field(default_factory=list)
    requires_revision: bool = False


class ReviewerOutput(BaseModel):
    passed: bool
    findings: list[ReviewerFindingItem] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)
