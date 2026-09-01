"""Company identity and local ticker-search models."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

FRIENDLY_NAME_OVERRIDES = {
    "AAPL": "Apple Inc.",
    "AMAT": "Applied Materials Inc.",
    "AMZN": "Amazon.com, Inc.",
    "GOOG": "Alphabet Inc.",
    "GOOGL": "Alphabet Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "RKLB": "Rocket Lab Corp.",
}

CORPORATE_SUFFIXES = {
    "INC": "Inc.",
    "INC.": "Inc.",
    "CORP": "Corp.",
    "CORP.": "Corp.",
    "CO": "Co.",
    "CO.": "Co.",
    "LTD": "Ltd.",
    "LTD.": "Ltd.",
    "PLC": "PLC",
    "LLC": "LLC",
    "LP": "LP",
    "N A": "N.A.",
    "NA": "N.A.",
}

LEGAL_SUFFIX_RE = re.compile(r"\s+/(?:[A-Z]{2,}|[A-Z]\.?[A-Z]?\.?)$", re.IGNORECASE)


class CompanyIdentity(BaseModel):
    ticker: str
    company_name: str
    exchange: str | None = None
    cik: str

    @property
    def cik_padded(self) -> str:
        return self.cik.zfill(10)

    @property
    def display_name(self) -> str:
        return friendly_company_name(self.company_name, ticker=self.ticker)


def friendly_company_name(company_name: str | None, *, ticker: str | None = None) -> str:
    if ticker and ticker.upper() in FRIENDLY_NAME_OVERRIDES:
        return FRIENDLY_NAME_OVERRIDES[ticker.upper()]
    if not company_name:
        return ""

    clean = LEGAL_SUFFIX_RE.sub("", company_name.strip())
    clean = re.sub(r"\s+", " ", clean)
    clean = _restore_dot_com(clean)
    words = clean.split(" ")
    if not words:
        return ""

    normalized_words = [word if word.isupper() and len(word) <= 4 else word.title() for word in words]
    normalized = " ".join(normalized_words)
    for suffix, replacement in CORPORATE_SUFFIXES.items():
        if normalized.upper().endswith(f" {suffix}"):
            return normalized[: -len(suffix)].rstrip() + f" {replacement}"
    return normalized


def _restore_dot_com(value: str) -> str:
    words = value.split(" ")
    for index, word in enumerate(words[1:], start=1):
        if word.upper() == "COM":
            previous = words[index - 1].rstrip(".")
            words[index - 1] = f"{previous}.com"
            del words[index]
            break
    return " ".join(words)


class TickerCacheMetadata(BaseModel):
    source_url: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    record_count: int


class TickerCache(BaseModel):
    metadata: TickerCacheMetadata
    companies: list[CompanyIdentity]
