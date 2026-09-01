"""Evidence records and citation helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from velox.models.tool_result import Freshness
from velox.models.warnings import WarningRecord


class EvidenceType(StrEnum):
    EARNINGS = "earnings"
    SEC_FILING = "sec_filing"
    COMPANY_FACT = "company_fact"
    NEWS = "news"
    QUOTE = "quote"
    PRIOR_REPORT = "prior_report"
    COMPANY_CONTEXT = "company_context"


class EvidenceRecord(BaseModel):
    evidence_id: str | None = None
    evidence_type: EvidenceType
    provider: str
    title: str
    source_url: str | None = None
    source_date: datetime | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    freshness: Freshness = Freshness.UNKNOWN
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_id_shape(self) -> EvidenceRecord:
        if self.evidence_id is not None and not self.evidence_id.startswith("E"):
            raise ValueError("evidence_id must start with 'E'")
        return self


class SourceTableRow(BaseModel):
    evidence_id: str
    evidence_type: EvidenceType
    provider: str
    source_date: datetime | None = None
    captured_at: datetime
    title: str
    source_url: str | None = None


class EvidencePack(BaseModel):
    records: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[WarningRecord] = Field(default_factory=list)

    def assign_ids(self) -> EvidencePack:
        records = [
            record.model_copy(update={"evidence_id": f"E{index}"})
            for index, record in enumerate(self.records, start=1)
        ]
        return self.model_copy(update={"records": records})

    @property
    def citation_ids(self) -> set[str]:
        return {record.evidence_id for record in self.records if record.evidence_id is not None}

    def source_table(self) -> list[SourceTableRow]:
        return [
            SourceTableRow(
                evidence_id=record.evidence_id or "",
                evidence_type=record.evidence_type,
                provider=record.provider,
                source_date=record.source_date,
                captured_at=record.captured_at,
                title=record.title,
                source_url=record.source_url,
            )
            for record in self.records
            if record.evidence_id is not None
        ]

    def validate_citations(self, citation_ids: list[str]) -> list[str]:
        known_ids = self.citation_ids
        return [citation_id for citation_id in citation_ids if citation_id not in known_ids]
