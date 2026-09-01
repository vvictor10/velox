"""First-class retry and fallback records."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from velox.models.telemetry import FailureCategory


class RetryRecord(BaseModel):
    tool_name: str
    attempt_count: int
    reason: str
    failure_category: FailureCategory
    user_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FallbackRecord(BaseModel):
    primary_tool_name: str
    fallback_tool_name: str
    reason: str
    user_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
