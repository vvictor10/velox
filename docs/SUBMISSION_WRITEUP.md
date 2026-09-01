# Velox Submission Writeup

## Project Overview

Velox is a stock earnings research agent that helps a user prepare for upcoming public-company earnings. The user searches for a U.S. ticker, starts a research run, watches the agent move through visible workflow steps, reviews the final cited brief, and explicitly approves whether the report should be saved to memory.

The project focuses on the hard parts of agentic systems: control flow, structured state, tool usage, recoverable and non-recoverable failures, memory, tracing/evals, and a human approval boundary.

## Primer

My agent helps individual investors prepare for upcoming earnings in a web app, replacing the 1-2 hours of manual searching across earnings calendars, SEC filings, financial data sites, news, and analyst commentary. It researches a ticker on its own using ticker-search, earnings-calendar, SEC/company-facts, market-data, news, Mem0 memory, and LLM tools, hands off to the investor before saving or treating any output as an investment decision, and I will know it works when a user can generate a useful, source-grounded earnings preview brief in under 5 minutes for supported U.S. tickers, with visible tool usage, clear missing-data notes, and no unsupported investment recommendations.

## Framework

| Field | Velox Decision |
|---|---|
| Agent goal | Generate a source-grounded earnings preview brief for a public company ticker. |
| User surface | Streamlit web app with local ticker typeahead, progress states, report tabs, citations, telemetry, and approval controls. |
| Tools | Local SEC ticker cache, SEC EDGAR/company facts, Alpha Vantage, Finnhub fallback, Mem0, local snapshot export, LLM providers, LangSmith tracing/evals. |
| Memory | Stores only user-approved project-owned ticker reports, capped at 10 saved companies. |
| Agent roles | News theme analyst, delta analyst, risk analyst, brief drafter, and reviewer. |
| Human boundary | The agent can research, analyze, draft, and review autonomously, but saving memory requires explicit user approval. |
| Failure behavior | Tool failures are categorized, retried where appropriate, surfaced in progress/telemetry/tool ledger, and never hidden. |

## Architecture

Velox uses LangGraph as the orchestrator. The graph starts with ticker identity resolution, then gathers public evidence, loads prior approved memory, assembles a normalized evidence pack, checks minimum evidence, runs LLM-backed analysis, drafts a structured report, reviews it, and pauses at the Human Review Gate before saving.

Each provider call returns a shared `ToolResult` with status, timing, source, freshness, fallback state, failure category, data, and error. This lets the UI and telemetry display exactly what happened instead of hiding tool behavior behind a single answer.

## Agents

| Agent | Purpose |
|---|---|
| News Theme Agent | Groups recent headlines into earnings-relevant themes using only the supplied evidence. |
| Delta Agent | Compares the current evidence and brief against the prior approved report, when memory exists. |
| Risk Analyst Agent | Produces earnings-relevant risks and watch items with required evidence IDs. |
| Brief Drafter Agent | Builds the analyst-style earnings preview with citations and missing-data notes. |
| Reviewer Agent | Checks schema, citations, unsupported claims, missing warnings, stale-data disclosure, and no-investment-advice boundaries. |

## Tools And Data Sources

Velox avoids personal data. It does not use Kubera, brokerage accounts, portfolio data, bank data, or user holdings.

The app uses public/company data only:

| Source | Use |
|---|---|
| Local SEC ticker cache | Fast typeahead without remote calls on each keystroke. |
| SEC EDGAR | Company identity, submissions, and company facts context. |
| Alpha Vantage | Optional primary earnings/news/overview source. |
| Finnhub | Baseline and fallback earnings/news source. |
| Mem0 | Approved prior report memory for what-changed-since-last-time analysis. |
| Local JSON snapshot | Local mirror of approved report memory. |
| LangSmith | Development-time tracing and eval evidence. |

## Failure Handling

Failures are categorized into recoverable, degraded-continuable, and non-recoverable outcomes.

Recoverable failures, such as rate limits, temporary provider errors, and LLM schema misses, are retried once. If a fallback source is configured, the fallback is used and the run continues with explicit warnings. Degraded-continuable failures proceed only if the minimum evidence gate passes. Non-recoverable failures stop before drafting or saving.

The demo can force a visible Alpha Vantage news failure by setting `VELOX_DEMO_FORCE_ALPHA_NEWS_FAILURE=true`. This exercises retry, fallback, warning, telemetry, and tool-ledger behavior without depending on an actual provider outage.

## Human In The Loop

Velox includes a Human Review Gate. After the reviewer passes the brief, the app pauses and asks the user to approve saving. Until approval, no Mem0 write and no local snapshot export occurs. If the reviewer blocks the brief after repair/revision attempts, the save button remains disabled and the user sees the reviewer findings.

This makes the boundary explicit: the agent may operate autonomously on read-only research and drafting, but durable write actions require the human.

## Memory

Mem0 stores approved report snapshots by ticker/CIK. A later run retrieves the prior approved memory and uses it for delta analysis. If no prior report exists, the app reports that neutrally. If Mem0 lookup fails, the app does not pretend there was no prior report; it records `lookup_failed`, continues without delta memory, and shows the issue.

## Tracing And Evals

LangSmith tracing is optional at runtime and enabled when `LANGSMITH_API_KEY` and `LANGSMITH_TRACING=true` are present. Local telemetry remains available even without LangSmith.

The project includes deterministic evaluators for final status, required sections, citations, warning disclosure, no investment advice, approval boundary, and expected LLM spans. Model selection used prompt-specific fixtures across Nebius and Fireworks, then pinned default models per agent step.

## Iterations And Learnings

Key iterations:

- Moved ticker search to a local SEC cache to avoid wasting provider calls during typeahead.
- Added Alpha Vantage pacing after observing free-tier frequency limits.
- Treated Alpha Vantage as optional and Finnhub as a real fallback path.
- Tightened prompts to require evidence grounding, JSON schemas, citation IDs, missing-data behavior, and no trading advice.
- Added reviewer repair/revision handling so citation metadata mismatches can be resolved once before blocking approval.
- Improved UI transparency with live progress text, telemetry, warnings, and a visible Human Review Gate.

Main learning: the prompt is only one part of the system. The bigger work is making state, tools, failures, review, and human approval explicit enough that the agent remains understandable when something goes wrong.

## Demo Plan

The demo should show:

1. Ticker search and selection.
2. Live progress through the research workflow.
3. Tool ledger and telemetry.
4. A completed cited earnings preview.
5. Reviewer behavior and Human Review Gate.
6. Approve-and-save to Mem0.
7. Rerun the same ticker to show prior approved memory and delta analysis.
8. Optional forced Alpha Vantage news failure to show retry/fallback transparency.

## Future Enhancements

The submission MVP intentionally keeps a few production-hardening ideas out of scope: graph concurrency, durable checkpoint/resume, timeout/run-budget telemetry, in-app saved-memory management, saved-report fallback evidence with stale-data timestamps, hosted LangSmith datasets, and LLM-as-judge qualitative evals.
