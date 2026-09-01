"""Normalized news and news-theme models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from velox.models.warnings import WarningRecord


class NewsItem(BaseModel):
    headline: str
    source: str
    published_at: datetime
    url: str | None = None
    summary: str | None = None
    related_tickers: list[str] = Field(default_factory=list)
    provider_sentiment: dict[str, float | str] = Field(default_factory=dict)
    source_provider: str
    source_evidence_id: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NewsTheme(BaseModel):
    theme: str
    summary: str
    supporting_evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class NewsSnapshot(BaseModel):
    ticker: str
    items: list[NewsItem] = Field(default_factory=list)
    themes: list[NewsTheme] = Field(default_factory=list)
    warnings: list[WarningRecord] = Field(default_factory=list)

    @property
    def has_recent_news(self) -> bool:
        return bool(self.items)
