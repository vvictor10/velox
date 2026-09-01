"""HTTP helpers for provider adapters."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import requests

from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolResult


def get_json_tool_result(
    *,
    tool_name: str,
    source: str,
    url: str,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: int = 30,
) -> ToolResult:
    """GET JSON and wrap all outcomes in ToolResult."""

    started_at = datetime.now(UTC)
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"Request timed out: {exc}",
            failure_category=FailureCategory.RECOVERABLE,
        )
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        category = (
            FailureCategory.RECOVERABLE
            if status_code in {408, 425, 429, 500, 502, 503, 504}
            else FailureCategory.DEGRADED_CONTINUABLE
        )
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"HTTP {status_code}: {exc}",
            failure_category=category,
        )
    except ValueError as exc:
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"Response was not valid JSON: {exc}",
            failure_category=FailureCategory.DEGRADED_CONTINUABLE,
        )
    except requests.RequestException as exc:
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"Request failed: {exc}",
            failure_category=FailureCategory.RECOVERABLE,
        )

    provider_error = _provider_error(payload)
    if provider_error:
        category = (
            FailureCategory.RECOVERABLE
            if "rate" in provider_error.lower() or "frequency" in provider_error.lower()
            else FailureCategory.DEGRADED_CONTINUABLE
        )
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=provider_error,
            failure_category=category,
            data=_payload_shape(payload),
        )

    return ToolResult.success(
        tool_name=tool_name,
        source=source,
        started_at=started_at,
        data=payload,
    )


def get_csv_tool_result(
    *,
    tool_name: str,
    source: str,
    url: str,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: int = 30,
) -> ToolResult:
    """GET CSV and wrap all outcomes in ToolResult."""

    started_at = datetime.now(UTC)
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        text = response.text.strip()
    except requests.Timeout as exc:
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"Request timed out: {exc}",
            failure_category=FailureCategory.RECOVERABLE,
        )
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        category = (
            FailureCategory.RECOVERABLE
            if status_code in {408, 425, 429, 500, 502, 503, 504}
            else FailureCategory.DEGRADED_CONTINUABLE
        )
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"HTTP {status_code}: {exc}",
            failure_category=category,
        )
    except requests.RequestException as exc:
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error=f"Request failed: {exc}",
            failure_category=FailureCategory.RECOVERABLE,
        )

    if not text:
        return ToolResult.failure(
            tool_name=tool_name,
            source=source,
            started_at=started_at,
            error="CSV response was empty.",
            failure_category=FailureCategory.DEGRADED_CONTINUABLE,
        )
    if text.startswith("{"):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": text[:500]}
        provider_error = _provider_error(payload)
        if provider_error:
            return ToolResult.failure(
                tool_name=tool_name,
                source=source,
                started_at=started_at,
                error=provider_error,
                failure_category=FailureCategory.RECOVERABLE,
                data=_payload_shape(payload),
            )

    rows = list(csv.DictReader(StringIO(text)))
    return ToolResult.success(
        tool_name=tool_name,
        source=source,
        started_at=started_at,
        data={"rows": rows, "row_count": len(rows)},
    )


def _provider_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("Error Message", "Note", "Information", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _payload_shape(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {"keys": list(payload.keys())[:20]}
    if isinstance(payload, list):
        return {"items": len(payload)}
    return {"type": type(payload).__name__}
