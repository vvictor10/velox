"""Tracing helpers for local telemetry and optional LangSmith integration."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from velox.config import AppSettings, load_settings

P = ParamSpec("P")
R = TypeVar("R")


def traceable_step(
    *,
    name: str,
    run_type: str = "chain",
    metadata: dict[str, Any] | None = None,
    settings: AppSettings | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a function with LangSmith tracing when configured.

    The returned function is unchanged when LangSmith is unavailable or disabled,
    which keeps the app shippable for reviewers who only provide core API keys.
    """

    resolved_settings = settings or load_settings()
    safe_metadata = {
        **resolved_settings.public_trace_metadata(),
        **(metadata or {}),
    }

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        if not resolved_settings.langsmith_enabled:
            return func

        try:
            from langsmith import traceable
        except ImportError:
            return func

        resolved_settings.apply_langsmith_environment()
        traced = traceable(name=name, run_type=run_type, metadata=safe_metadata)(func)

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return traced(*args, **kwargs)

        return wrapper

    return decorator


def build_run_metadata(
    *,
    settings: AppSettings,
    run_id: str,
    ticker: str | None = None,
    company_name: str | None = None,
    cik: str | None = None,
    final_status: str | None = None,
    completed_with_warnings: bool | None = None,
) -> dict[str, Any]:
    """Build non-secret trace metadata for a graph run."""

    metadata = {
        **settings.public_trace_metadata(),
        "run_id": run_id,
    }
    optional_fields = {
        "ticker": ticker,
        "company_name": company_name,
        "cik": cik,
        "final_status": final_status,
        "completed_with_warnings": completed_with_warnings,
    }
    metadata.update({key: value for key, value in optional_fields.items() if value is not None})
    return metadata
