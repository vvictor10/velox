from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox.config import load_settings
from velox.workflow.graph import invoke_minimal_graph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="AAPL")
    args = parser.parse_args()

    state = invoke_minimal_graph(args.ticker, load_settings())
    print(
        {
            "status": state.status.value,
            "company": state.company.company_name if state.company else None,
            "evidence_count": len(state.evidence_pack.records),
            "tool_count": len(state.tool_results),
            "warnings": len(state.warnings),
            "retries": len(state.retry_records),
            "fallbacks": len(state.fallback_records),
            "prior_memory_status": state.prior_memory.status.value if state.prior_memory else None,
            "progress": state.progress_text,
            "earnings_forward": state.earnings.has_forward_calendar if state.earnings else None,
            "news_items": len(state.news.items) if state.news else None,
        }
    )


if __name__ == "__main__":
    main()
