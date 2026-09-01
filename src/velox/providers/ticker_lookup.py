"""Local ticker cache refresh and typeahead search."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from velox.models.company import CompanyIdentity, TickerCache, TickerCacheMetadata
from velox.paths import COMPANY_TICKERS_PATH

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUPPORTED_EXCHANGES = {"Nasdaq", "NYSE", "NYSE Arca", "NYSE American"}


def refresh_ticker_cache(
    *,
    destination: Path = COMPANY_TICKERS_PATH,
    source_url: str = SEC_TICKERS_URL,
    timeout_seconds: int = 30,
    user_agent: str | None = None,
) -> TickerCache:
    headers = {"User-Agent": user_agent} if user_agent else None
    response = requests.get(source_url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    cache = normalize_sec_ticker_payload(response.json(), source_url=source_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(cache.model_dump_json(indent=2), encoding="utf-8")
    return cache


def normalize_sec_ticker_payload(payload: dict[str, Any], *, source_url: str) -> TickerCache:
    fields = payload.get("fields", [])
    data = payload.get("data", [])
    field_index = {field: index for index, field in enumerate(fields)}
    companies: list[CompanyIdentity] = []

    for row in data:
        if not isinstance(row, list):
            continue
        try:
            cik = str(row[field_index["cik"]])
            company_name = str(row[field_index["name"]]).strip()
            ticker = str(row[field_index["ticker"]]).strip().upper()
            exchange = str(row[field_index["exchange"]]).strip()
        except (KeyError, IndexError):
            continue
        if not ticker or not company_name:
            continue
        companies.append(
            CompanyIdentity(
                ticker=ticker,
                company_name=company_name,
                exchange=exchange,
                cik=cik,
            )
        )

    companies.sort(key=lambda company: (company.ticker, company.company_name))
    return TickerCache(
        metadata=TickerCacheMetadata(
            source_url=source_url,
            captured_at=datetime.now(UTC),
            record_count=len(companies),
        ),
        companies=companies,
    )


def load_ticker_cache(path: Path = COMPANY_TICKERS_PATH) -> TickerCache:
    return TickerCache.model_validate_json(path.read_text(encoding="utf-8"))


def search_tickers(
    query: str,
    *,
    cache: TickerCache | None = None,
    path: Path = COMPANY_TICKERS_PATH,
    limit: int = 10,
    major_exchanges_only: bool = True,
) -> list[CompanyIdentity]:
    if not query.strip():
        return []
    loaded_cache = cache or load_ticker_cache(path)
    normalized = query.strip().upper()
    scored_matches: list[tuple[int, str, CompanyIdentity]] = []

    for company in loaded_cache.companies:
        if major_exchanges_only and company.exchange not in SUPPORTED_EXCHANGES:
            continue
        score = _match_score(company, normalized)
        if score is not None:
            scored_matches.append((score, company.ticker, company))
    scored_matches.sort(key=lambda item: (item[0], item[1]))
    return [company for _, _, company in scored_matches[:limit]]


def cache_summary(path: Path = COMPANY_TICKERS_PATH) -> dict[str, Any]:
    cache = load_ticker_cache(path)
    return {
        "source_url": cache.metadata.source_url,
        "captured_at": cache.metadata.captured_at.isoformat(),
        "record_count": cache.metadata.record_count,
        "path": str(path),
    }


def dump_search_results(query: str, path: Path = COMPANY_TICKERS_PATH) -> str:
    results = search_tickers(query, path=path)
    return json.dumps([result.model_dump() for result in results], indent=2)


def _match_score(company: CompanyIdentity, normalized_query: str) -> int | None:
    company_name = company.company_name.upper()
    if company.ticker == normalized_query:
        return 0
    if company.ticker.startswith(normalized_query):
        return 1
    if company_name.startswith(normalized_query):
        return 2
    if normalized_query in company_name:
        return 3
    return None
