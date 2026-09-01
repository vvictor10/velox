# Velox - Stock Earnings Research Agent

Velox is a Week 3 agentic AI project for generating source-grounded earnings preview briefs for public-company tickers. It is a lean agent orchestration application, not a brokerage, advisor, or trading product.

## What This Repo Contains

| Area | Location | Purpose |
|---|---|---|
| PRD | [docs/PRD.md](docs/PRD.md) | Reviewer-facing primer, framework table, product requirements, safety boundaries, and success criteria. |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical architecture, graph flow, tool strategy, telemetry, and data presentation. |
| Processed outputs | [data/processed/](data/processed/) | Approved report snapshots and generated outputs. |
| App surface | [frontend/](frontend/) | Streamlit app entry point. |
| Agent implementation | [src/](src/) | LangGraph orchestration, tools, memory snapshots, and report generation. |
| Tests | [tests/](tests/) | Focused tests for tool fallbacks, safety boundaries, and report structure. |

## Current Scope

Velox lets a user search for a U.S. public ticker, gathers public earnings/company/news context, compares against prior project-owned Mem0 memory, and produces a reviewed earnings preview with risk flags, missing-data notes, visible tool usage, and human approval before saving. See [docs/PRD.md](docs/PRD.md) for the reviewer-facing scope.

The application uses public market/company data tools, Mem0 memory, and local JSON snapshot exports. Kubera, brokerage accounts, portfolio connections, and personal user data are out of scope.

## Local Setup Goal

The app should be runnable from GitHub with environment variables. Copy `.env.example` to `.env`, add provider keys, install dependencies, and run the Streamlit app.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/streamlit run frontend/app.py
```

Before the first run, refresh the local ticker cache if `data/static/company_tickers.json` is missing:

```bash
.venv/bin/python scripts/refresh_tickers.py
```

## Demo Failure Path

To demonstrate visible tool failure and fallback behavior without waiting for a real provider outage, set this optional flag in `.env`:

```bash
VELOX_DEMO_FORCE_ALPHA_NEWS_FAILURE=true
```

With Finnhub enabled, Velox records the forced Alpha Vantage news failure, retries it, falls back to Finnhub company news when available, and surfaces the degraded path in progress, warnings, telemetry, and the tool ledger.
