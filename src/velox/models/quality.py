"""Qualitative report assessment models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QualityFactor(BaseModel):
    name: str
    score: float = Field(ge=0, le=1)
    rationale: str


class QualityAssessment(BaseModel):
    overall_score: float = Field(ge=0, le=1)
    judge_score: float = Field(ge=0, le=1)
    confidence_label: str
    summary: str
    factors: list[QualityFactor] = Field(default_factory=list)
    improvement_notes: list[str] = Field(default_factory=list)
    judge_model_id: str | None = None
    prompt_version: str | None = None
    method: str = "LLM judge score adjusted by deterministic guardrails and RunState telemetry."
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None
