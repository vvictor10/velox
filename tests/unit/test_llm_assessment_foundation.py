from __future__ import annotations

from pathlib import Path

from velox.analysis.llm_client import LlmProvider, ModelInfo
from velox.analysis.model_assessment import (
    STAGES,
    _deterministic_eval,
    assessment_paths,
    candidate_models_from_inventory,
)
from velox.analysis.prompts import load_prompt
from velox.analysis.schemas import (
    BriefOutput,
    NewsThemeOutput,
    ReviewerOutput,
    RiskOutput,
)
from velox.config import load_settings


def test_all_stage_prompts_load_with_versions() -> None:
    for stage in STAGES:
        prompt = load_prompt(stage.prompt_name)
        assert prompt.name == stage.prompt_name
        assert prompt.version
        assert "Return ONLY a valid JSON object" in prompt.body


def test_structured_schema_examples_validate() -> None:
    NewsThemeOutput.model_validate(
        {
            "themes": [
                {
                    "theme": "AI product cycle",
                    "summary": "Recent news centers on AI product launches.",
                    "supporting_evidence_ids": ["E2"],
                    "confidence": 0.8,
                }
            ],
            "missing_data_notes": [],
        }
    )
    RiskOutput.model_validate(
        {
            "risks": [
                {
                    "risk": "Margin pressure",
                    "severity": "medium",
                    "rationale": "Management discussed margin pressure.",
                    "supporting_evidence_ids": ["E3"],
                    "watch_item": "Watch gross margin commentary.",
                }
            ],
            "missing_data_notes": [],
        }
    )
    BriefOutput.model_validate(
        {
            "headline": "Apple earnings setup",
            "sections": [{"title": "Setup", "body": "Earnings date is listed. [E1]", "citation_ids": ["E1"]}],
            "warnings": [],
            "source_ids_used": ["E1"],
        }
    )
    ReviewerOutput.model_validate(
        {
            "passed": True,
            "findings": [],
            "revision_instructions": [],
        }
    )


def test_config_loads_llm_base_urls_and_pinned_models(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """NEBIUS_BASE_URL=https://example.test/nebius
FIREWORKS_BASE_URL=https://example.test/fireworks
VELOX_NEWS_THEME_MODEL=news-model
VELOX_REVIEWER_MODEL=reviewer-model
"""
    )

    settings = load_settings(env_file)

    assert settings.nebius_base_url == "https://example.test/nebius"
    assert settings.fireworks_base_url == "https://example.test/fireworks"
    assert settings.velox_news_theme_model == "news-model"
    assert settings.velox_reviewer_model == "reviewer-model"


def test_candidate_models_prefers_known_open_model_families() -> None:
    inventory = {
        LlmProvider.FIREWORKS: [
            ModelInfo(provider=LlmProvider.FIREWORKS, model_id="accounts/fireworks/models/other"),
            ModelInfo(provider=LlmProvider.FIREWORKS, model_id="accounts/fireworks/models/deepseek-v3p1"),
        ],
        LlmProvider.NEBIUS: [
            ModelInfo(provider=LlmProvider.NEBIUS, model_id="meta-llama/Llama-3.3-70B-Instruct"),
        ],
    }

    candidates = candidate_models_from_inventory(inventory, max_per_provider=1)

    assert candidates == [
        (LlmProvider.FIREWORKS, "accounts/fireworks/models/deepseek-v3p1"),
        (LlmProvider.NEBIUS, "meta-llama/Llama-3.3-70B-Instruct"),
    ]


def test_assessment_paths_support_stable_labels() -> None:
    markdown_path, raw_path = assessment_paths("GPT OSS / Fast Pass")

    assert markdown_path.name == "llm_assessment_results_gpt_oss_fast_pass.md"
    assert raw_path.name == "llm_assessment_results_gpt_oss_fast_pass.json"


def test_deterministic_eval_checks_citations_and_advice_boundary() -> None:
    result = _deterministic_eval(
        {
            "sections": [
                {
                    "body": "The company should not be treated as a guaranteed winner.",
                    "citation_ids": ["E1", "E99"],
                }
            ]
        },
        evidence_ids={"E1"},
    )

    assert result["citations_valid"] is False
    assert result["invalid_citation_ids"] == ["E99"]
    assert result["advice_boundary_valid"] is False
    assert "guaranteed" in result["prohibited_terms_found"]


def test_deterministic_eval_requires_structural_section_citations() -> None:
    result = _deterministic_eval(
        {
            "sections": [
                {
                    "title": "Earnings Snapshot",
                    "body": "The report date is listed. (E1)",
                    "citation_ids": [],
                }
            ],
            "source_ids_used": ["E1"],
        },
        evidence_ids={"E1"},
    )

    assert result["citations_valid"] is False
    assert result["sections_missing_structural_citations"] == ["Earnings Snapshot"]


def test_deterministic_eval_requires_structured_warnings() -> None:
    result = _deterministic_eval(
        {
            "sections": [
                {
                    "title": "Warnings",
                    "body": "Alpha Vantage disabled; Finnhub fallback used.",
                    "citation_ids": [],
                }
            ],
            "warnings": [],
        },
        evidence_ids={"E1"},
        expected_warnings={"Alpha Vantage disabled; Finnhub fallback used."},
    )

    assert result["warnings_valid"] is False
    assert result["missing_structured_warnings"] == ["Alpha Vantage disabled; Finnhub fallback used."]
