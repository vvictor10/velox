"""Normalized earnings data models."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from velox.models.warnings import WarningRecord


class AnnouncementTiming(StrEnum):
    BEFORE_MARKET_OPEN = "before_market_open"
    AFTER_MARKET_CLOSE = "after_market_close"
    DURING_MARKET_HOURS = "during_market_hours"
    UNKNOWN = "unknown"


class EarningsEvent(BaseModel):
    report_date: date | None = None
    timing: AnnouncementTiming = AnnouncementTiming.UNKNOWN
    fiscal_quarter: int | None = None
    fiscal_year: int | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    source_provider: str
    source_evidence_id: str | None = None


class HistoricalEarningsQuarter(BaseModel):
    period: date | None = None
    fiscal_quarter: int | None = None
    fiscal_year: int | None = None
    eps_actual: float | None = None
    eps_estimate: float | None = None
    revenue_actual: float | None = None
    revenue_estimate: float | None = None
    surprise: float | None = None
    surprise_percent: float | None = None
    source_provider: str
    source_evidence_id: str | None = None


class EarningsSnapshot(BaseModel):
    ticker: str
    next_event: EarningsEvent | None = None
    history: list[HistoricalEarningsQuarter] = Field(default_factory=list)
    warnings: list[WarningRecord] = Field(default_factory=list)

    @property
    def has_forward_calendar(self) -> bool:
        return self.next_event is not None and self.next_event.report_date is not None

    @property
    def has_historical_earnings(self) -> bool:
        return bool(self.history)
