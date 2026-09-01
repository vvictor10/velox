"""Model inventory and fixture assessment helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from velox.analysis.llm_client import LlmProvider, ModelInfo, VeloxLlmClient
from velox.analysis.prompts import load_prompt
from velox.analysis.schemas import (
    BriefOutput,
    DeltaOutput,
    NewsThemeOutput,
    ReviewerOutput,
    RiskOutput,
)
from velox.config import AppSettings
from velox.paths import LLM_ASSESSMENT_RAW_PATH, LOCAL_SPIKES_DIR


class LlmStage(BaseModel):
    name: str
    prompt_name: str
    schema_name: str


STAGES = [
    LlmStage(name="news_theme", prompt_name="news_theme", schema_name="NewsThemeOutput"),
    LlmStage(name="delta", prompt_name="delta", schema_name="DeltaOutput"),
    LlmStage(name="risk", prompt_name="risk", schema_name="RiskOutput"),
    LlmStage(name="brief_drafter", prompt_name="brief_drafter", schema_name="BriefOutput"),
    LlmStage(name="reviewer", prompt_name="reviewer", schema_name="ReviewerOutput"),
]

SCHEMAS = {
    "NewsThemeOutput": NewsThemeOutput,
    "DeltaOutput": DeltaOutput,
    "RiskOutput": RiskOutput,
    "BriefOutput": BriefOutput,
    "ReviewerOutput": ReviewerOutput,
}

MODEL_INVENTORY_PATH = LOCAL_SPIKES_DIR / "llm_model_inventory.md"
LLM_ASSESSMENT_PATH = LOCAL_SPIKES_DIR / "llm_assessment_results.md"


def assessment_paths(label: str | None = None) -> tuple[Path, Path]:
    if not label:
        return LLM_ASSESSMENT_PATH, LLM_ASSESSMENT_RAW_PATH
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).strip("_").lower()
    if not safe_label:
        return LLM_ASSESSMENT_PATH, LLM_ASSESSMENT_RAW_PATH
    return (
        LOCAL_SPIKES_DIR / f"llm_assessment_results_{safe_label}.md",
        LOCAL_SPIKES_DIR / f"llm_assessment_results_{safe_label}.json",
    )


def inventory_models(settings: AppSettings) -> dict[LlmProvider, list[ModelInfo]]:
    client = VeloxLlmClient(settings)
    inventory: dict[LlmProvider, list[ModelInfo]] = {}
    for provider in _available_providers(settings):
        inventory[provider] = client.list_models(provider)
    return inventory


def write_model_inventory(inventory: dict[LlmProvider, list[ModelInfo]]) -> Path:
    MODEL_INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# LLM Model Inventory", ""]
    for provider, models in inventory.items():
        lines.extend([f"## {provider.value}", "", "| Model ID | Owned By |", "|---|---|"])
        for model in models:
            lines.append(f"| `{model.model_id}` | {model.owned_by or ''} |")
        lines.append("")
    MODEL_INVENTORY_PATH.write_text("\n".join(lines), encoding="utf-8")
    return MODEL_INVENTORY_PATH


def candidate_models_from_inventory(
    inventory: dict[LlmProvider, list[ModelInfo]],
    *,
    max_per_provider: int = 5,
) -> list[tuple[LlmProvider, str]]:
    candidates: list[tuple[LlmProvider, str]] = []
    preferred_terms = ("llama", "qwen", "deepseek", "mixtral", "kimi", "gpt-oss")
    for provider, models in inventory.items():
        preferred = [
            model
            for model in models
            if any(term in model.model_id.lower() for term in preferred_terms)
        ]
        selected = (preferred or models)[:max_per_provider]
        candidates.extend((provider, model.model_id) for model in selected)
    return candidates


def run_fixture_assessment(
    settings: AppSettings,
    *,
    candidates: Iterable[tuple[LlmProvider, str]],
) -> list[dict[str, Any]]:
    client = VeloxLlmClient(settings)
    results: list[dict[str, Any]] = []
    fixture = _shared_fixture()
    for provider, model_id in candidates:
        for stage in STAGES:
            prompt = load_prompt(stage.prompt_name)
            schema = SCHEMAS[stage.schema_name]
            result = client.call_structured(
                provider=provider,
                model_id=model_id,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                system_prompt=prompt.body,
                user_payload=fixture[stage.name],
                output_schema=schema,
            )
            results.append(
                {
                    "stage": stage.name,
                    "provider": result.provider.value,
                    "model_id": result.model_id,
                    "prompt_version": result.prompt_version,
                    "schema_valid": result.schema_valid,
                    **_deterministic_eval(
                        result.output,
                        evidence_ids={"E1", "E2", "E3"},
                        expected_warnings=set(fixture[stage.name].get("warnings", [])),
                    ),
                    "duration_ms": result.telemetry.duration_ms,
                    "input_tokens": result.telemetry.input_tokens,
                    "output_tokens": result.telemetry.output_tokens,
                    "error": result.error,
                    "output": result.output,
                }
            )
    return results


def write_assessment_results(results: list[dict[str, Any]], *, label: str | None = None) -> Path:
    assessment_path, raw_path = assessment_paths(label)
    assessment_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    lines = [
        "# LLM Assessment Results",
        "",
        "| Stage | Provider | Model | Schema Valid | Citations Valid | Warnings Valid | Advice Boundary | Duration ms | Input Tokens | Output Tokens | Error |",
        "|---|---|---|---|---|---|---|---:|---:|---:|---|",
    ]
    for result in results:
        lines.append(
            "| {stage} | {provider} | `{model_id}` | {schema_valid} | {citations_valid} | "
            "{warnings_valid} | {advice_boundary_valid} | {duration_ms} | {input_tokens} | {output_tokens} | {error} |".format(
                stage=result["stage"],
                provider=result["provider"],
                model_id=result["model_id"],
                schema_valid=result["schema_valid"],
                citations_valid=result["citations_valid"],
                warnings_valid=result["warnings_valid"],
                advice_boundary_valid=result["advice_boundary_valid"],
                duration_ms=result["duration_ms"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                error=_compact(result["error"]),
            )
        )
    assessment_path.write_text("\n".join(lines), encoding="utf-8")
    return assessment_path


def _available_providers(settings: AppSettings) -> list[LlmProvider]:
    providers: list[LlmProvider] = []
    if settings.nebius_api_key:
        providers.append(LlmProvider.NEBIUS)
    if settings.fireworks_api_key:
        providers.append(LlmProvider.FIREWORKS)
    return providers


def _shared_fixture() -> dict[str, dict[str, Any]]:
    evidence = [
        {
            "evidence_id": "E1",
            "type": "earnings",
            "provider": "Finnhub",
            "title": "Earnings calendar",
            "payload": {"date": "2026-10-29", "epsEstimate": 1.5, "revenueEstimate": 100.0},
        },
        {
            "evidence_id": "E2",
            "type": "news",
            "provider": "Finnhub",
            "title": "Company launches AI product",
            "payload": {"headline": "Company launches AI product before earnings"},
        },
        {
            "evidence_id": "E3",
            "type": "sec_filing",
            "provider": "SEC",
            "title": "Recent 10-Q",
            "payload": {"note": "Management discussed margin pressure."},
        },
    ]
    return {
        "news_theme": {"ticker": "AAPL", "evidence": evidence},
        "delta": {
            "ticker": "AAPL",
            "prior_report_status": "found",
            "prior_report_summary": "Prior report focused on services growth.",
            "current_evidence": evidence,
        },
        "risk": {
            "ticker": "AAPL",
            "evidence": evidence,
            "news_themes": [
                {"theme": "AI product cycle", "supporting_evidence_ids": ["E2"]},
            ],
            "delta_findings": [
                {"category": "changed", "finding": "AI launch is newly prominent.", "supporting_evidence_ids": ["E2"]},
            ],
        },
        "brief_drafter": {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "evidence": evidence,
            "news_themes": [{"theme": "AI product cycle", "supporting_evidence_ids": ["E2"]}],
            "risk_findings": [{"risk": "Margin pressure", "supporting_evidence_ids": ["E3"]}],
            "warnings": ["Alpha Vantage disabled; Finnhub fallback used."],
        },
        "reviewer": {
            "ticker": "AAPL",
            "evidence_ids": ["E1", "E2", "E3"],
            "tool_warnings": ["Alpha Vantage disabled; Finnhub fallback used."],
            "draft": {
                "sections": [
                    {
                        "title": "Earnings Setup",
                        "body": "Apple is expected to report earnings on 2026-10-29. [E1]",
                        "citation_ids": ["E1"],
                    }
                ]
            },
        },
    }


def _compact(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    return text[:180] + "..." if len(text) > 180 else text


def _deterministic_eval(
    output: dict[str, Any] | None,
    *,
    evidence_ids: set[str],
    expected_warnings: set[str] | None = None,
) -> dict[str, Any]:
    if output is None:
        return {
            "citations_valid": False,
            "invalid_citation_ids": [],
            "warnings_valid": False,
            "missing_structured_warnings": sorted(expected_warnings or []),
            "advice_boundary_valid": False,
            "prohibited_terms_found": [],
        }
    citation_ids = _collect_citation_ids(output)
    invalid_citation_ids = sorted({citation for citation in citation_ids if citation not in evidence_ids})
    prohibited_terms_found = _prohibited_terms(output)
    missing_structured_warnings = _missing_structured_warnings(output, expected_warnings or set())
    return {
        "citations_valid": not invalid_citation_ids and not _sections_missing_structural_citations(output),
        "invalid_citation_ids": invalid_citation_ids,
        "sections_missing_structural_citations": _sections_missing_structural_citations(output),
        "warnings_valid": not missing_structured_warnings,
        "missing_structured_warnings": missing_structured_warnings,
        "advice_boundary_valid": not prohibited_terms_found,
        "prohibited_terms_found": prohibited_terms_found,
        "reviewer_action_valid": _reviewer_action_valid(output),
    }


def _collect_citation_ids(value: Any) -> list[str]:
    citations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"citation_ids", "supporting_evidence_ids", "source_ids_used"} and isinstance(nested, list):
                citations.extend(str(item) for item in nested)
            else:
                citations.extend(_collect_citation_ids(nested))
    elif isinstance(value, list):
        for item in value:
            citations.extend(_collect_citation_ids(item))
    return citations


def _prohibited_terms(output: dict[str, Any]) -> list[str]:
    text = json.dumps(output).lower()
    terms = ["buy", "sell", "hold", "price target", "guaranteed", "you should invest"]
    return [term for term in terms if term in text]


def _sections_missing_structural_citations(output: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    sections = output.get("sections")
    if not isinstance(sections, list):
        return missing
    for section in sections:
        if not isinstance(section, dict):
            continue
        body = str(section.get("body") or "")
        inline_ids = set(re.findall(r"\bE\d+\b", body))
        structural_ids = {str(item) for item in section.get("citation_ids", [])}
        if inline_ids and not inline_ids.issubset(structural_ids):
            missing.append(str(section.get("title") or "Untitled"))
    return missing


def _missing_structured_warnings(output: dict[str, Any], expected_warnings: set[str]) -> list[str]:
    if not expected_warnings:
        return []
    actual_warnings = output.get("warnings")
    if not isinstance(actual_warnings, list):
        return sorted(expected_warnings)
    actual_text = "\n".join(str(warning).lower() for warning in actual_warnings)
    return sorted(warning for warning in expected_warnings if warning.lower() not in actual_text)


def _reviewer_action_valid(output: dict[str, Any]) -> bool:
    if "passed" not in output:
        return True
    if output.get("passed") is True:
        return True
    findings = output.get("findings", [])
    revision_instructions = output.get("revision_instructions", [])
    has_revision_finding = any(
        isinstance(finding, dict) and finding.get("requires_revision") is True
        for finding in findings
    )
    return has_revision_finding or bool(revision_instructions)
