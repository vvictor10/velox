"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr

ProviderStatus = Literal["available", "missing", "optional_missing"]


class StartupCheck(BaseModel):
    """A startup check that can be displayed without exposing secrets."""

    name: str
    status: ProviderStatus
    message: str


class AppSettings(BaseModel):
    """Runtime settings for Velox.

    Secrets are stored as SecretStr so accidental repr/printing does not leak
    credential values during local debugging or trace metadata assembly.
    """

    app_env: str = "local"
    nebius_api_key: SecretStr | None = None
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    fireworks_api_key: SecretStr | None = None
    fireworks_base_url: str = "https://api.fireworks.ai/inference/v1"
    velox_news_theme_model: str | None = None
    velox_delta_model: str | None = None
    velox_risk_model: str | None = None
    velox_brief_model: str | None = None
    velox_reviewer_model: str | None = None
    velox_quality_judge_model: str | None = None
    mem0_api_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    finnhub_api_key: SecretStr | None = None
    sec_user_agent: str | None = None
    langsmith_api_key: SecretStr | None = None
    langsmith_tracing: bool = True
    langsmith_project: str = "velox"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    alpha_vantage_live_enabled: bool = False
    alpha_vantage_min_seconds_between_calls: float = Field(default=1.1, ge=0)
    alpha_vantage_daily_request_budget: int = Field(default=25, ge=0)
    velox_demo_force_alpha_news_failure: bool = False
    finnhub_live_enabled: bool = True
    sec_live_enabled: bool = True
    workflow_version: str = "0.1.0"
    node_timeout_seconds: int = Field(default=45, ge=1)
    run_budget_seconds: int = Field(default=300, ge=10)

    @property
    def langsmith_enabled(self) -> bool:
        return self.langsmith_tracing and _has_secret(self.langsmith_api_key)

    @property
    def has_primary_llm(self) -> bool:
        return _has_secret(self.nebius_api_key) or _has_secret(self.fireworks_api_key)

    @property
    def has_market_data(self) -> bool:
        return _has_secret(self.alpha_vantage_api_key)

    def startup_checks(self) -> list[StartupCheck]:
        checks = [
            StartupCheck(
                name="LLM provider",
                status="available" if self.has_primary_llm else "missing",
                message=(
                    "Nebius or Fireworks key found."
                    if self.has_primary_llm
                    else "Add NEBIUS_API_KEY or FIREWORKS_API_KEY before LLM-backed analysis."
                ),
            ),
            StartupCheck(
                name="Alpha Vantage",
                status="available" if self.has_market_data else "optional_missing",
                message=(
                    "Alpha Vantage key found; live usage is controlled by ALPHA_VANTAGE_LIVE_ENABLED."
                    if self.has_market_data
                    else "Alpha Vantage is optional; Finnhub and SEC are the baseline public-data sources."
                ),
            ),
            StartupCheck(
                name="SEC user agent",
                status="available" if bool(self.sec_user_agent) else "missing",
                message=(
                    "SEC user agent configured."
                    if self.sec_user_agent
                    else "Add SEC_USER_AGENT for SEC EDGAR API requests."
                ),
            ),
            StartupCheck(
                name="Mem0",
                status="available" if _has_secret(self.mem0_api_key) else "missing",
                message=(
                    "Mem0 key found."
                    if _has_secret(self.mem0_api_key)
                    else "Add MEM0_API_KEY before prior-report memory features."
                ),
            ),
            StartupCheck(
                name="Finnhub",
                status="available" if _has_secret(self.finnhub_api_key) else "missing",
                message=(
                    "Finnhub key found."
                    if _has_secret(self.finnhub_api_key)
                    else "Add FINNHUB_API_KEY for baseline earnings/news research."
                ),
            ),
            StartupCheck(
                name="LangSmith",
                status="available" if self.langsmith_enabled else "optional_missing",
                message=(
                    "LangSmith tracing/evals enabled."
                    if self.langsmith_enabled
                    else "LangSmith is optional; local telemetry remains enabled."
                ),
            ),
        ]
        return checks

    def public_trace_metadata(self) -> dict[str, str | bool | int]:
        """Return non-secret metadata safe for local logs and LangSmith traces."""

        return {
            "app_env": self.app_env,
            "workflow_version": self.workflow_version,
            "langsmith_enabled": self.langsmith_enabled,
            "nebius_configured": _has_secret(self.nebius_api_key),
            "fireworks_configured": _has_secret(self.fireworks_api_key),
            "alpha_vantage_configured": _has_secret(self.alpha_vantage_api_key),
            "alpha_vantage_live_enabled": self.alpha_vantage_live_enabled,
            "alpha_vantage_daily_request_budget": self.alpha_vantage_daily_request_budget,
            "demo_force_alpha_news_failure": self.velox_demo_force_alpha_news_failure,
            "finnhub_configured": _has_secret(self.finnhub_api_key),
            "finnhub_live_enabled": self.finnhub_live_enabled,
            "sec_live_enabled": self.sec_live_enabled,
            "mem0_configured": _has_secret(self.mem0_api_key),
            "node_timeout_seconds": self.node_timeout_seconds,
            "run_budget_seconds": self.run_budget_seconds,
        }

    def apply_langsmith_environment(self) -> None:
        """Populate LangSmith env vars for LangChain/LangGraph integrations."""

        if not self.langsmith_enabled:
            os.environ["LANGSMITH_TRACING"] = "false"
            return

        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = self.langsmith_endpoint
        os.environ["LANGSMITH_API_KEY"] = self.langsmith_api_key.get_secret_value()


def load_settings(env_file: str | Path = ".env") -> AppSettings:
    """Load app settings from .env and process environment variables."""

    env_values = dotenv_values(env_file)

    def get(name: str, default: str | None = None) -> str | None:
        value = env_values.get(name)
        if value is not None:
            return value
        return os.getenv(name, default)

    return AppSettings(
        app_env=get("APP_ENV", "local") or "local",
        nebius_api_key=_secret_from_value(get("NEBIUS_API_KEY")),
        nebius_base_url=get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
        or "https://api.tokenfactory.nebius.com/v1/",
        fireworks_api_key=_secret_from_value(get("FIREWORKS_API_KEY")),
        fireworks_base_url=get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
        or "https://api.fireworks.ai/inference/v1",
        velox_news_theme_model=_blank_to_none(get("VELOX_NEWS_THEME_MODEL")),
        velox_delta_model=_blank_to_none(get("VELOX_DELTA_MODEL")),
        velox_risk_model=_blank_to_none(get("VELOX_RISK_MODEL")),
        velox_brief_model=_blank_to_none(get("VELOX_BRIEF_MODEL")),
        velox_reviewer_model=_blank_to_none(get("VELOX_REVIEWER_MODEL")),
        velox_quality_judge_model=_blank_to_none(get("VELOX_QUALITY_JUDGE_MODEL")),
        mem0_api_key=_secret_from_value(get("MEM0_API_KEY")),
        alpha_vantage_api_key=_secret_from_value(get("ALPHA_VANTAGE_API_KEY")),
        finnhub_api_key=_secret_from_value(get("FINNHUB_API_KEY")),
        sec_user_agent=_blank_to_none(get("SEC_USER_AGENT")),
        langsmith_api_key=_secret_from_value(get("LANGSMITH_API_KEY")),
        langsmith_tracing=_bool_from_value(get("LANGSMITH_TRACING"), default=True),
        langsmith_project=get("LANGSMITH_PROJECT", "velox") or "velox",
        langsmith_endpoint=get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        or "https://api.smith.langchain.com",
        alpha_vantage_live_enabled=_bool_from_value(
            get("ALPHA_VANTAGE_LIVE_ENABLED"),
            default=False,
        ),
        alpha_vantage_min_seconds_between_calls=float(
            get("ALPHA_VANTAGE_MIN_SECONDS_BETWEEN_CALLS", "1.1") or "1.1"
        ),
        alpha_vantage_daily_request_budget=int(
            get("ALPHA_VANTAGE_DAILY_REQUEST_BUDGET", "25") or "25"
        ),
        velox_demo_force_alpha_news_failure=_bool_from_value(
            get("VELOX_DEMO_FORCE_ALPHA_NEWS_FAILURE"),
            default=False,
        ),
        finnhub_live_enabled=_bool_from_value(get("FINNHUB_LIVE_ENABLED"), default=True),
        sec_live_enabled=_bool_from_value(get("SEC_LIVE_ENABLED"), default=True),
        workflow_version=get("WORKFLOW_VERSION", "0.1.0") or "0.1.0",
        node_timeout_seconds=int(get("NODE_TIMEOUT_SECONDS", "45") or "45"),
        run_budget_seconds=int(get("RUN_BUDGET_SECONDS", "300") or "300"),
    )


def _secret_from_value(value: str | None) -> SecretStr | None:
    value = _blank_to_none(value)
    return SecretStr(value) if value else None


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().strip('"').strip("'")
    return stripped or None


def _bool_from_value(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _has_secret(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value().strip())
