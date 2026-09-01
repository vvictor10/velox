from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox.analysis.llm_client import LlmProvider
from velox.analysis.model_assessment import (
    inventory_models,
    run_fixture_assessment,
    write_assessment_results,
)
from velox.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate as provider:model_id. Example: fireworks:accounts/fireworks/models/deepseek-v3p1",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional label for output files, e.g. qwen-glm or gpt-oss.",
    )
    args = parser.parse_args()
    settings = load_settings()
    if args.candidate:
        candidates = [_parse_candidate(candidate) for candidate in args.candidate]
    else:
        inventory = inventory_models(settings)
        candidates = [
            (provider, models[0].model_id)
            for provider, models in inventory.items()
            if models
        ]
    results = run_fixture_assessment(settings, candidates=candidates)
    path = write_assessment_results(results, label=args.label)
    print(f"Wrote LLM assessment results to {path}")


def _parse_candidate(raw: str) -> tuple[LlmProvider, str]:
    provider, model_id = raw.split(":", 1)
    return LlmProvider(provider), model_id


if __name__ == "__main__":
    main()
