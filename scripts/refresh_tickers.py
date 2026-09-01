from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox.config import load_settings
from velox.providers.ticker_lookup import refresh_ticker_cache


def main() -> None:
    settings = load_settings()
    cache = refresh_ticker_cache(user_agent=settings.sec_user_agent)
    print(
        f"Refreshed {cache.metadata.record_count} tickers from "
        f"{cache.metadata.source_url} into data/static/company_tickers.json"
    )


if __name__ == "__main__":
    main()
