from __future__ import annotations

from pathlib import Path

from velox.config import load_settings
from velox.models.telemetry import RunTelemetry, SpanKind, SpanStatus, TelemetrySpan
from velox.observability import build_run_metadata, traceable_step


def test_load_settings_enables_langsmith_when_key_present(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """NEBIUS_API_KEY=nebius-test
ALPHA_VANTAGE_API_KEY=alpha-test
SEC_USER_AGENT=Velox test@example.com
LANGSMITH_API_KEY=langsmith-test
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=velox-test
"""
    )

    settings = load_settings(env_file)

    assert settings.langsmith_enabled is True
    assert settings.langsmith_project == "velox-test"
    assert settings.has_primary_llm is True
    assert settings.has_market_data is True
    assert settings.alpha_vantage_live_enabled is False
    assert settings.alpha_vantage_daily_request_budget == 25


def test_load_settings_keeps_langsmith_optional(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LANGSMITH_TRACING=true\n")

    settings = load_settings(env_file)
    check_by_name = {check.name: check for check in settings.startup_checks()}

    assert settings.langsmith_enabled is False
    assert check_by_name["LangSmith"].status == "optional_missing"


def test_startup_checks_identify_missing_required_and_optional_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("")

    settings = load_settings(env_file)
    check_by_name = {check.name: check for check in settings.startup_checks()}

    assert check_by_name["LLM provider"].status == "missing"
    assert check_by_name["SEC user agent"].status == "missing"
    assert check_by_name["Mem0"].status == "missing"
    assert check_by_name["Finnhub"].status == "missing"
    assert check_by_name["Alpha Vantage"].status == "optional_missing"
    assert check_by_name["LangSmith"].status == "optional_missing"


def test_startup_checks_accept_core_keys_without_optional_alpha_or_langsmith(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """FIREWORKS_API_KEY=fireworks-test
SEC_USER_AGENT=Velox test@example.com
MEM0_API_KEY=mem0-test
FINNHUB_API_KEY=finnhub-test
"""
    )

    settings = load_settings(env_file)
    check_by_name = {check.name: check for check in settings.startup_checks()}

    assert check_by_name["LLM provider"].status == "available"
    assert check_by_name["SEC user agent"].status == "available"
    assert check_by_name["Mem0"].status == "available"
    assert check_by_name["Finnhub"].status == "available"
    assert check_by_name["Alpha Vantage"].status == "optional_missing"
    assert check_by_name["LangSmith"].status == "optional_missing"


def test_load_settings_can_enable_alpha_vantage_live(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """ALPHA_VANTAGE_LIVE_ENABLED=true
ALPHA_VANTAGE_MIN_SECONDS_BETWEEN_CALLS=2.5
ALPHA_VANTAGE_DAILY_REQUEST_BUDGET=7
"""
    )

    settings = load_settings(env_file)

    assert settings.alpha_vantage_live_enabled is True
    assert settings.alpha_vantage_min_seconds_between_calls == 2.5
    assert settings.alpha_vantage_daily_request_budget == 7


def test_load_settings_can_enable_demo_failure_flag(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VELOX_DEMO_FORCE_ALPHA_NEWS_FAILURE=true\n")

    settings = load_settings(env_file)

    assert settings.velox_demo_force_alpha_news_failure is True
    assert settings.public_trace_metadata()["demo_force_alpha_news_failure"] is True


def test_load_settings_reads_optional_quality_judge_model(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VELOX_QUALITY_JUDGE_MODEL=accounts/fireworks/models/gpt-oss-120b\n")

    settings = load_settings(env_file)

    assert settings.velox_quality_judge_model == "accounts/fireworks/models/gpt-oss-120b"


def test_traceable_step_noops_when_langsmith_disabled(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LANGSMITH_TRACING=false\n")
    settings = load_settings(env_file)

    def sample(value: int) -> int:
        return value + 1

    decorated = traceable_step(name="sample", settings=settings)(sample)

    assert decorated(1) == 2


def test_run_metadata_excludes_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NEBIUS_API_KEY=secret-value\nLANGSMITH_API_KEY=trace-secret\n")
    settings = load_settings(env_file)

    metadata = build_run_metadata(settings=settings, run_id="run-1", ticker="AAPL", cik="320193")

    assert metadata["run_id"] == "run-1"
    assert metadata["ticker"] == "AAPL"
    assert "secret-value" not in str(metadata)
    assert "trace-secret" not in str(metadata)


def test_run_telemetry_summary_tracks_slowest_and_counts() -> None:
    telemetry = RunTelemetry(run_id="run-1")
    tool_span = TelemetrySpan(
        name="fetch_news",
        kind=SpanKind.TOOL,
        retry_count=1,
        fallback_used=True,
    ).finish(SpanStatus.FALLBACK_USED)
    llm_span = TelemetrySpan(name="reviewer", kind=SpanKind.LLM).finish()

    telemetry.add_span(tool_span)
    telemetry.add_span(llm_span)
    summary = telemetry.finish("completed_with_warnings", completed_with_warnings=True).public_summary()

    assert summary["retry_count"] == 1
    assert summary["fallback_count"] == 1
    assert summary["completed_with_warnings"] is True
    assert summary["slowest_span"] in {"fetch_news", "reviewer"}
