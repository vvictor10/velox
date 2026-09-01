"""Shared result contract for every tool/provider call."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from velox.models.telemetry import FailureCategory


class ToolStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRIED = "retried"
    FALLBACK_USED = "fallback_used"
    SKIPPED = "skipped"
    LOOKUP_FAILED = "lookup_failed"


class Freshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ToolResult(BaseModel):
    tool_name: str
    status: ToolStatus
    failure_category: FailureCategory = FailureCategory.NONE
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    duration_ms: int | None = None
    source: str
    freshness: Freshness = Freshness.UNKNOWN
    fallback_used: bool = False
    fallback_reason: str | None = None
    data: dict[str, Any] | list[Any] | None = None
    error: str | None = None

    @classmethod
    def success(
        cls,
        *,
        tool_name: str,
        source: str,
        started_at: datetime,
        data: dict[str, Any] | list[Any] | None,
        freshness: Freshness = Freshness.CURRENT,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> ToolResult:
        ended_at = datetime.now(UTC)
        return cls(
            tool_name=tool_name,
            status=ToolStatus.FALLBACK_USED if fallback_used else ToolStatus.SUCCESS,
            failure_category=FailureCategory.NONE,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=_duration_ms(started_at, ended_at),
            source=source,
            freshness=freshness,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            data=data,
        )

    @classmethod
    def failure(
        cls,
        *,
        tool_name: str,
        source: str,
        started_at: datetime,
        error: str,
        failure_category: FailureCategory,
        status: ToolStatus = ToolStatus.FAILED,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        data: dict[str, Any] | list[Any] | None = None,
        freshness: Freshness = Freshness.UNKNOWN,
    ) -> ToolResult:
        ended_at = datetime.now(UTC)
        return cls(
            tool_name=tool_name,
            status=status,
            failure_category=failure_category,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=_duration_ms(started_at, ended_at),
            source=source,
            freshness=freshness,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            data=data,
            error=error,
        )


def _duration_ms(started_at: datetime, ended_at: datetime) -> int:
    return int((ended_at - started_at).total_seconds() * 1000)
