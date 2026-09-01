from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox.config import load_settings
from velox.evals.evaluators import evaluate_state
from velox.paths import LOCAL_SPIKES_DIR
from velox.workflow.graph import invoke_research_graph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--output", default="langsmith_eval_local_results.json")
    args = parser.parse_args()

    settings = load_settings()
    settings.apply_langsmith_environment()
    tickers = args.ticker or ["AAPL"]
    results = []
    for ticker in tickers:
        state = invoke_research_graph(ticker, settings)
        suite = evaluate_state(f"research_graph_{ticker}", state)
        results.append(
            {
                "ticker": ticker,
                "run_id": state.run_id,
                "status": state.status.value,
                "progress_text": state.progress_text,
                "warnings": [warning.model_dump(mode="json") for warning in state.warnings],
                "passed": suite.passed,
                "score": suite.score,
                "results": [result.model_dump() for result in suite.results],
                "telemetry": state.telemetry.public_summary() if state.telemetry else None,
            }
        )

    output_path = LOCAL_SPIKES_DIR / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote local LangSmith-style eval results to {output_path}")


if __name__ == "__main__":
    main()
