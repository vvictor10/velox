"""User-visible warnings and failure disclosure models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from velox.models.telemetry import FailureCategory


class WarningSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class WarningRecord(BaseModel):
    code: str
    message: str
    severity: WarningSeverity = WarningSeverity.WARNING
    source: str | None = None
    failure_category: FailureCategory | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
