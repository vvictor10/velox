"""Filesystem paths used by Velox."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DATA_DIR = DATA_DIR / "static"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
BRIEFS_DIR = PROCESSED_DATA_DIR / "briefs"
LOCAL_DOCS_DIR = PROJECT_ROOT / "docs" / "local"
LOCAL_SPIKES_DIR = LOCAL_DOCS_DIR / "spikes"

COMPANY_TICKERS_PATH = STATIC_DATA_DIR / "company_tickers.json"
DATA_SPIKE_RESULTS_PATH = LOCAL_SPIKES_DIR / "data_spike_results.md"
LLM_ASSESSMENT_RAW_PATH = LOCAL_SPIKES_DIR / "llm_assessment_results.json"
