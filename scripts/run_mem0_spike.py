from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox.config import load_settings
from velox.models.report import EarningsBrief, ReportSection
from velox.providers.mem0_store import Mem0ReportStore
from velox.providers.ticker_lookup import load_ticker_cache


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="AAPL")
    parser.add_argument(
        "--approved-save",
        action="store_true",
        help="Actually save a synthetic approved report memory to Mem0/local snapshot.",
    )
    args = parser.parse_args()

    settings = load_settings()
    company = next(
        company
        for company in load_ticker_cache().companies
        if company.ticker == args.ticker.strip().upper()
    )
    store = Mem0ReportStore(settings)
    memory, lookup_result = store.lookup_prior_report(company)
    print(
        {
            "lookup_status": lookup_result.status.value,
            "prior_memory_status": memory.status.value,
            "prior_memory_timestamp": memory.report_timestamp.isoformat()
            if memory.report_timestamp
            else None,
        }
    )

    if not args.approved_save:
        print("Save skipped. Re-run with --approved-save to exercise the approved write path.")
        return

    brief = EarningsBrief(
        ticker=company.ticker,
        company_name=company.company_name,
        sections=[
            ReportSection(
                title="Synthetic Mem0 Spike Brief",
                body="This public-data-only synthetic brief validates the approved memory save path.",
                citation_ids=[],
            )
        ],
    )
    save_result = store.save_approved_report(
        company=company,
        brief=brief,
        approved=True,
        existing_memory_id=memory.memory_id,
    )
    print(
        {
            "save_status": save_result.tool_result.status.value,
            "saved_snapshot_path": str(save_result.saved_snapshot_path)
            if save_result.saved_snapshot_path
            else None,
            "saved_memory_status": save_result.memory.status.value,
        }
    )


if __name__ == "__main__":
    main()
