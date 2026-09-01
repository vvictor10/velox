"""Telemetry models for graph, tool, and LLM runtime measurements."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SpanKind(StrEnum):
    GRAPH = "graph"
    TOOL = "tool"
    LLM = "llm"
    DECISION = "decision"
    RENDERER = "renderer"


class SpanStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRIED = "retried"
    FALLBACK_USED = "fallback_used"
    SKIPPED = "skipped"


class FailureCategory(StrEnum):
    NONE = "none"
    RECOVERABLE = "recoverable"
    DEGRADED_CONTINUABLE = "degraded_continuable"
    NON_RECOVERABLE = "non_recoverable"


class TelemetrySpan(BaseModel):
    name: str
    kind: SpanKind
    status: SpanStatus = SpanStatus.SUCCESS
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    duration_ms: int | None = None
    failure_category: FailureCategory = FailureCategory.NONE
    retry_count: int = 0
    fallback_used: bool = False
    provider: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    message: str | None = None

    def finish(self, status: SpanStatus | None = None) -> TelemetrySpan:
        ended = datetime.now(UTC)
        return self.model_copy(
            update={
                "ended_at": ended,
                "duration_ms": int((ended - self.started_at).total_seconds() * 1000),
                "status": status or self.status,
            }
        )


class RunTelemetry(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    spans: list[TelemetrySpan] = Field(default_factory=list)
    completed_with_warnings: bool = False
    final_status: str | None = None

    def add_span(self, span: TelemetrySpan) -> None:
        self.spans.append(span)

    def finish(self, final_status: str, completed_with_warnings: bool = False) -> RunTelemetry:
        return self.model_copy(
            update={
                "ended_at": datetime.now(UTC),
                "final_status": final_status,
                "completed_with_warnings": completed_with_warnings,
            }
        )

    @property
    def total_duration_ms(self) -> int | None:
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() * 1000)

    @property
    def slowest_span(self) -> TelemetrySpan | None:
        completed_spans = [span for span in self.spans if span.duration_ms is not None]
        if not completed_spans:
            return None
        return max(completed_spans, key=lambda span: span.duration_ms or 0)

    @property
    def retry_count(self) -> int:
        return sum(span.retry_count for span in self.spans)

    @property
    def fallback_count(self) -> int:
        return sum(1 for span in self.spans if span.fallback_used)

    def public_summary(self) -> dict[str, object]:
        slowest = self.slowest_span
        return {
            "run_id": self.run_id,
            "final_status": self.final_status,
            "completed_with_warnings": self.completed_with_warnings,
            "total_duration_ms": self.total_duration_ms,
            "retry_count": self.retry_count,
            "fallback_count": self.fallback_count,
            "slowest_span": slowest.name if slowest else None,
            "slowest_span_duration_ms": slowest.duration_ms if slowest else None,
        }
