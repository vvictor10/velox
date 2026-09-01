# Velox: Agentic Earnings Research Assistant

## Project Overview

Velox is a stock earnings research agent that helps a user prepare for upcoming public-company earnings. The user searches for a U.S. ticker, starts a research run, watches the agent move through visible workflow steps, reviews the final cited brief, and explicitly approves whether the report should be saved to memory.

The project focuses on the hard parts of agentic systems: control flow, structured state, tool usage, recoverable and non-recoverable failures, memory, tracing/evals, and a human approval boundary.

## Primer

My agent helps individual investors prepare for upcoming earnings in a web app, replacing the 1-2 hours of manual searching across earnings calendars, SEC filings, financial data sites, news, and analyst commentary. It researches a ticker on its own using ticker-search, earnings-calendar, SEC/company-facts, market-data, news, Mem0 memory, and LLM tools, hands off to the investor before saving or treating any output as an investment decision, and I know it works when a user can generate a useful, source-grounded earnings preview brief in under 5 minutes for supported U.S. tickers, with visible tool usage, clear missing-data notes, and no unsupported investment recommendations.

## Architecture Diagrams

Architecture overview:

![Velox architecture overview](../assets/velox-architecture.png)

Agentic workflow:

![Velox agentic workflow](../assets/velox-agentic-workflow.jpeg)

## Product Flow

1. The user selects a ticker from local typeahead.
2. Velox initializes a `RunState` and resolves company identity from the local SEC-seeded ticker cache.
3. The graph collects public evidence from SEC EDGAR, Finnhub, and optionally Alpha Vantage.
4. Velox loads prior approved report memory from Mem0/local snapshot when available.
5. The system assembles a normalized evidence pack with run-scoped evidence IDs.
6. A minimum evidence gate stops weak runs before drafting.
7. LLM-backed agents produce news themes, delta findings, risk/watch items, and a cited draft brief.
8. A reviewer agent checks schema, citations, warning disclosure, unsupported claims, stale-data handling, and investment-advice boundaries.
9. Repairable citation or content issues get one repair/revision attempt.
10. If the reviewer passes, the app pauses at a Human Review Gate.
11. The user approves or skips saving.
12. Approved reports are saved to Mem0 and mirrored to a local JSON snapshot.

## Tools And Data Sources

Velox uses only public or project-owned data. It does not use Kubera, brokerage accounts, bank data, portfolio holdings, or personal financial information.

| Source | Use |
|---|---|
| Local SEC ticker cache | Fast ticker/company typeahead without remote calls per keystroke. |
| SEC EDGAR | Company identity, CIK mapping, recent submissions, and company facts context. |
| Finnhub | Baseline earnings calendar, recent earnings surprises, and company news. |
| Alpha Vantage | Optional enrichment source for earnings history, estimates, overview, quote, and news sentiment metadata. |
| Mem0 | Prior approved report memory for what-changed-since-last-time analysis. |
| Local JSON snapshot | Local mirror of approved report memory. |
| Nebius / Fireworks | OpenAI-compatible LLM providers for prompt-specialized agent steps. |
| LangSmith | Optional tracing and evaluation evidence for graph, tool, and LLM behavior. |

## Agent Roles

| Agent | Responsibility |
|---|---|
| News Theme Agent | Groups recent headlines into earnings-relevant themes using only supplied evidence. |
| Delta Agent | Compares current evidence against the prior approved report when memory exists. |
| Risk Analyst Agent | Identifies earnings-relevant risks and watch items with required evidence IDs. |
| Brief Drafter Agent | Builds the analyst-style earnings preview with citations and missing-data notes. |
| Reviewer Agent | Checks citations, schema, unsupported claims, stale/missing-data disclosure, and safety boundaries. |

The implementation uses prompt-specialized roles rather than open-ended general agents. Deterministic work stays deterministic: ticker lookup, provider normalization, citation mapping, table rendering, chart preparation, and validation are handled in code.

## Prompt And Context Engineering

Each LLM-backed node has a curated prompt file under `src/velox/prompts/`. Prompts define the agent role, allowed evidence, output schema, citation requirements, missing-data behavior, and no-investment-advice boundary.

Context is intentionally scoped per node:

- News theme analysis receives normalized news items with evidence IDs.
- Delta analysis receives current evidence summaries plus prior approved memory when available.
- Risk analysis receives the evidence pack, news themes, delta output, earnings setup, company context, and warnings.
- Brief drafting receives validated evidence, analysis outputs, citation map, required report schema, and warnings.
- Reviewer receives the draft, evidence pack, tool ledger, warnings, schema expectations, and safety policy.

All LLM outputs are validated against structured schemas before downstream use. If schema or grounding validation fails, the workflow retries or stops/degrades according to the failure type.

## Model Selection

Velox evaluated Nebius Token Factory and Fireworks models with prompt-specific fixtures. The model decision was based on schema validity, citation validity, warning disclosure, safety-boundary behavior, latency, token usage, and qualitative output quality.

Submitted defaults:

| Substep | Provider | Model |
|---|---|---|
| News theme analysis | Fireworks | `accounts/fireworks/models/gpt-oss-120b` |
| Delta analysis | Nebius | `openai/gpt-oss-120b` |
| Risk analysis | Fireworks | `accounts/fireworks/models/gpt-oss-120b` |
| Brief drafting | Fireworks | `accounts/fireworks/models/gpt-oss-120b` |
| Reviewer | Nebius | `openai/gpt-oss-120b` |

The main lesson from model testing was that prompt structure mattered as much as model family. Tightened prompts that required JSON-only output, exact evidence IDs, explicit missing-data treatment, and no trading advice improved reliability across providers.

## Failure Handling

Velox categorizes failures before deciding how to continue:

| Category | Meaning | Handling |
|---|---|---|
| Recoverable | Temporary issue such as timeout, rate limit, or malformed LLM JSON. | Retry once, then fallback or stop depending on the node. |
| Degraded-continuable | Missing optional data where the report can still be useful if disclosed. | Continue only if minimum evidence passes and warnings are shown. |
| Non-recoverable | The run cannot safely produce or save a report. | Stop or interrupt with a user-facing reason. |

Silent fallback is not allowed. The UI shows retry/fallback messages in progress, warnings, telemetry, and the tool ledger. A demo flag can force Alpha Vantage news failure so the fallback behavior can be demonstrated reliably.

## Human In The Loop

Velox has a Human Review Gate. The agent can research, analyze, draft, and review autonomously, but durable write actions require explicit human approval. Until approval, Velox does not write to Mem0 and does not export the local approved-report snapshot.

If the reviewer blocks the brief because of unsupported claims, missing citations, hidden warnings, stale-data issues, or investment-advice boundary violations, the save action remains unavailable and reviewer findings are shown to the user.

## Memory

Velox saves only approved project-owned report snapshots. Each saved memory includes ticker/company identity, report timestamp, summary, risks, watch items, warnings, source metadata, prompt versions, and model IDs. A future run can retrieve the prior approved memory and produce a delta section that separates new, changed, unchanged, stale, and missing-prior findings.

If no prior report exists, the app treats that as a neutral no-memory state. If Mem0 lookup fails, Velox does not pretend no memory exists; it records `lookup_failed`, continues without prior memory, and discloses the issue.

## Tracing And Evals

LangSmith is optional at runtime. When enabled, it traces the parent run, graph/tool/LLM spans, provider availability, reviewer decisions, and memory operations. Local telemetry remains available regardless of LangSmith.

The project includes deterministic evaluators for:

- final status.
- required report sections.
- valid citations.
- warning disclosure.
- no silent fallback.
- no prohibited investment advice.
- approval-before-save boundary.
- expected LLM trace spans.

This gives the project testable evidence that the agent is not just producing text, but following the intended trajectory and safety contract.

## Iterations And Learnings

Important iterations:

- Moved ticker search to a local SEC cache to avoid spending provider quota during typeahead.
- Added Alpha Vantage pacing after observing free-tier frequency responses.
- Treated Finnhub as a real fallback path for earnings/news rather than a placeholder.
- Tightened prompts around evidence grounding, JSON schemas, citations, missing-data behavior, and no trading advice.
- Added reviewer repair/revision handling for citation metadata mismatches and content issues.
- Improved the UI with animated progress, completed-step history, tables, charts, telemetry, warnings, and the Human Review Gate.

Main learning: the prompt is only one part of the agent. The larger design challenge is making state, tools, failures, review, memory, and human approval explicit enough that the system remains understandable when something goes wrong.

## Current MVP Scope

Completed for submission:

- Stateful LangGraph workflow.
- Local ticker typeahead.
- Public evidence collection and normalization.
- Retry/fallback handling with user-visible warnings.
- Prompt-specialized LLM agents with structured outputs.
- Reviewer checks and repair/revision loop.
- Human Review Gate before memory writes.
- Mem0 approved report memory plus local snapshot mirror.
- Streamlit UI with progress, report tabs, charts, sources, telemetry, and eval checklist.
- Optional LangSmith tracing and local eval runner.
- Reviewer-facing PRD, architecture docs, diagrams, demo script, and README.

Tomorrow's live-demo work:

- Generate 2-3 fresh sample reports from supported tickers when Alpha Vantage quota is available.
- Save at least one approved report and rerun it to show prior-memory delta behavior.
- Record the under-5-minute demo video.

## Future Enhancements

These are intentionally outside the submission MVP:

- Run independent provider calls concurrently and parallelize news-theme/delta analysis before risk analysis.
- Add durable graph checkpoint/resume for interrupted runs.
- Add timeout and run-budget telemetry for cancelled or skipped nodes.
- Add in-app clear-old-reports controls for managing the 10-company memory cap.
- Add saved-report fallback evidence with explicit stale-data timestamps.
- Add hosted LangSmith datasets, trajectory evals, and LLM-as-judge quality evals.
