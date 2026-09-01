# Architecture: Velox Stock Earnings Research Agent

## Overview

Velox uses a stateful agent workflow to turn a selected U.S. public-company ticker into an earnings preview brief. The architecture is intentionally built around the hard parts of agentic systems: control flow, state, tool failure, and human approval.

## Architecture Diagram

- Overall architecture Mermaid source: [architecture.mmd](/Users/vvictor/Personal/Projects/AI%20Projects/velox/docs/architecture.mmd)
- Runtime agent flow Mermaid source: [agent-flow.mmd](/Users/vvictor/Personal/Projects/AI%20Projects/velox/docs/agent-flow.mmd)
- Runtime agent flow notes: [AGENT_FLOW.md](/Users/vvictor/Personal/Projects/AI%20Projects/velox/docs/AGENT_FLOW.md)

PNG/SVG exports should be generated from the Mermaid sources once the flow is stable.

## Core Components

| Component | Responsibility | Implementation Direction |
|---|---|---|
| Web UI | Typeahead ticker search, progress timeline, tool-call log, structured tables, final brief, telemetry, and approval controls. | Streamlit. |
| Orchestrator | Owns graph state, calls each node/tool, handles retries, records telemetry, and manages approval boundary. | LangGraph state graph. |
| Ticker Search | Performs local typeahead over a checked-in ticker/company lookup file. | Seed from SEC `company_tickers_exchange.json`; no runtime market-data API calls for keystrokes. |
| Earnings Data | Retrieves next earnings event, recent reported quarters, EPS/revenue estimates when available, actuals, and surprise history. | Alpha Vantage MCP/direct REST primary; Finnhub fallback when configured. |
| Company Context | Retrieves public company identity, CIK mapping, company facts, and recent filing metadata. | SEC EDGAR APIs. |
| News | Retrieves recent company news/headlines as public evidence with timestamps, sources, URLs, and summaries. | Alpha Vantage MCP/direct REST `NEWS_SENTIMENT` primary; Finnhub company-news fallback when configured. |
| Analysis Stage | Runs prompt-specialized analysis substeps: news themes and prior-report delta in parallel, then risk analysis after those outputs are available. | Shared LLM wrapper with per-substep prompts, schemas, retries, fallback model support, and telemetry. |
| Memory / Prior Report | Loads prior approved report memory for delta analysis and saves approved snapshots after human approval. | Mem0 primary memory; local JSON snapshot export. |
| Reviewer | Checks unsupported claims, missing source labels, stale data, and financial-safety boundary violations. | Separate LLM call or deterministic checklist. |
| Tracing / Evals | Captures graph runs, tool calls, agent spans, retries, fallback decisions, prompt/model metadata, and offline eval results. | Optional LangSmith integration; app still runs with local telemetry when disabled. |

## Tooling Strategy

- Ticker typeahead must use a local lookup file, not a runtime market-data API. The seed source is SEC `company_tickers_exchange.json`, normalized into a small project file with ticker, company name, exchange, and CIK.
- Alpha Vantage MCP/direct REST is an enhancement data source when configured and enabled, especially for earnings history, earnings estimates, company overview, quote, and news sentiment tools. It should not be used for routine ticker typeahead, and development defaults keep live Alpha Vantage calls disabled to preserve free-tier request budget.
- Finnhub plus SEC can support the base MVP evidence path. Finnhub provides earnings calendar, recent earnings surprises, company profile, and company news; SEC provides identity, filings, and company facts. Alpha Vantage enriches the report when request budget allows.
- Direct SEC EDGAR API calls provide public company ticker/CIK mapping, company facts, and recent filing metadata.
- Mem0 stores approved project-owned ticker memories so future runs can compare the current brief against prior findings. If Mem0 lookup fails, continue with `prior_report_status=lookup_failed`, not `missing`, and show the warning in the tool ledger. Saves are upserts keyed by normalized ticker/CIK so Velox keeps at most one current approved report per company.
- LangGraph coordinates the multi-step workflow, maintains run state, records tool-call status, and exposes progress events.
- LangSmith is used for development-time tracing and offline evals. It should trace the full graph, nested tool calls, nested LLM calls, retries, fallback decisions, and reviewer outcomes. If `LANGSMITH_API_KEY` is missing, tracing is disabled and local telemetry remains the source of user-facing runtime data.
- LLM providers can be mixed by role when keys are available, such as one model for analysis and another for review. During testing, each substep should be pinned to a specific provider/model/prompt version.
- Direct API fallbacks are acceptable for shippability when an MCP server is not configured, but the UI should still display those calls as tools with source, status, and freshness metadata.

## Agent Design Strategy

Velox balances latency, cost, and accuracy per workflow step instead of using one model or technique everywhere. Deterministic work stays deterministic: ticker lookup, provider normalization, citation mapping, table rendering, chart preparation, and most validation do not need LLM calls.

LLMs are reserved for judgment or language tasks:

- news theme analysis: smaller/fast structured-output model if accuracy is sufficient.
- delta analysis: mid-strength model with strict citations and schema.
- risk analysis: stronger reasoning model if spike results show clear quality improvement.
- brief drafting: model chosen for grounded writing and schema adherence.
- reviewer: most reliable checker we can afford, supported by deterministic citation/schema checks.

Retries and fallback models are used deliberately because they improve resilience but increase latency and cost. Spike telemetry should guide the final provider/model choice for each substep, and the submitted configuration should pin those choices for reproducibility.

## Prompt Strategy

Each LLM-backed node should use a curated system prompt written for that node's job, not a shared generic assistant prompt. Prompts should define the node role, required input fields, allowed evidence, expected output schema, safety boundaries, and refusal/missing-data behavior.

Initial prompt targets:

- Risk analysis prompt: identify earnings-relevant risks and watch items from provided evidence only.
- News theme prompt: classify headlines into concise earnings-relevant themes without inventing facts.
- Delta prompt: compare current findings against prior saved memory and separate new, changed, unchanged, and stale items.
- Brief drafting prompt: assemble the final report in the required section structure with source labels and missing-data notes.
- Reviewer prompt: flag unsupported claims, stale data, missing sources, and investment-advice boundary violations.

Prompt versions should be stored as source files so the project writeup can describe what was used and how the prompts evolved.

## LangSmith Tracing And Evals

LangSmith is an observability and evaluation layer for Velox, not a required product dependency. The Streamlit app should remain usable without LangSmith credentials, while development and reviewer demonstration runs can use LangSmith to prove the agentic behavior is visible and testable.

Tracing should cover:

- one parent trace per ticker research run.
- graph node spans for evidence collection, evidence assembly, minimum evidence gate, analysis, drafting, review, approval wait, and memory save.
- tool spans for local ticker lookup, SEC, Alpha Vantage, Finnhub fallback, Mem0 lookup, Mem0 save, and local snapshot export.
- LLM spans for news theme analysis, delta analysis, risk analysis, brief drafting, and reviewer.
- decision spans for retry, fallback, degraded continuation, non-recoverable stop, and human approval boundary.

Trace metadata should include:

- `run_id`, `ticker`, `company_name`, `cik`, and `workflow_version`.
- `prompt_version`, `provider`, and `model_id` for each LLM-backed node.
- `failure_category`, `retry_count`, `fallback_used`, `final_status`, and `completed_with_warnings`.
- latency, token usage, estimated cost when available, and slowest node/tool.

Offline evals should use a small Velox-specific dataset rather than generic benchmark prompts. Initial eval cases:

- happy path with sufficient earnings, SEC, news, and no prior memory.
- prior report present, where delta analysis must distinguish new, changed, unchanged, and stale findings.
- news unavailable, where the report can continue only with an explicit warning.
- earnings evidence missing, where the minimum evidence gate should stop before drafting.
- Mem0 lookup failure, where the run continues without falsely claiming no prior report exists.
- unsupported investment-advice claim, where reviewer must fail or request revision.
- malformed LLM JSON, where retry/fallback behavior must be visible.

Evaluator strategy:

- deterministic code evaluators for schema validity, required sections, valid citation IDs, missing-data warnings, no buy/sell/hold advice, and approval-before-save.
- trajectory evaluators for tool-use path correctness: expected tools called, retries/fallbacks disclosed, degraded continuation handled, and non-recoverable stops respected.
- LLM-as-judge evaluators only for qualitative dimensions such as risk specificity, analyst-style clarity, and whether cited evidence reasonably supports interpretive language.

LangSmith experiment results should be used during model selection to compare Nebius and Fireworks candidates for each LLM substep. The final submitted configuration should pin provider, model, and prompt version per substep based on Velox fixture performance across accuracy, latency, and cost.

## Graph Flow

1. `search_ticker`: typeahead search returns selectable U.S. public-company symbols from the local ticker lookup file.
2. `resolve_company_identity`: confirm the selected symbol still maps to a company, exchange, and SEC identifier before spending tokens.
3. Parallel evidence collection:
   - `fetch_earnings`: retrieve earnings date/history and available expectation fields.
   - `fetch_company_context`: retrieve SEC/company context and recent filing metadata.
   - `fetch_news`: retrieve recent public news/headlines.
   - `load_memory`: retrieve prior approved report memory from Mem0 and local snapshot if present.
4. `assemble_evidence_pack`: normalize tool outputs, source labels, freshness, warnings, and retry/fallback records into one structured evidence pack.
5. `minimum_evidence_gate`: stop with an explicit explanation if the evidence pack is too weak to support a grounded brief.
6. Parallel analysis substeps:
   - `analyze_news_themes`: classify headlines into earnings-relevant themes.
   - `analyze_delta`: compare current evidence with the last approved saved report when one exists.
7. `analyze_risks`: generate risk flags and watch items using the evidence pack plus news-theme and delta outputs.
8. `draft_brief`: assemble the structured earnings preview.
9. `review_brief`: check for unsupported claims, stale data, missing sources, schema problems, and safety issues.
10. `await_approval`: pause before saving/exporting.
11. `save_memory`: after approval, save to Mem0 and local JSON snapshot.
12. `manage_memory_limit`: if 10 ticker reports are already saved, ask the user to clear older reports before saving.

The orchestrator should run independent work concurrently where possible. Market data, company context, news, and prior-report lookup can run in parallel. After evidence assembly, news-theme analysis and delta analysis can also run in parallel. Risk analysis intentionally runs after those two because it benefits from both outputs.

## Earnings And News Data Contract

Earnings and news are core evidence sources, not decorative enrichments. Velox should treat them as first-class tool outputs with source labels, timestamps, freshness, and failure handling.

Earnings primary path:

- Finnhub earnings calendar for upcoming or expected earnings events in the base MVP path.
- Finnhub earnings surprises for recent reported quarters in the base MVP path.
- Alpha Vantage `EARNINGS`, `EARNINGS_ESTIMATES`, and `EARNINGS_CALENDAR` as enhancement sources when live Alpha Vantage is enabled and budget allows.

Earnings fallback path:

- Alpha Vantage can backfill longer history, analyst estimate data, and richer metadata when enabled.
- SEC recent 10-Q/10-K/8-K filing metadata remains available for context, but SEC does not replace a forward-looking earnings calendar.

Earnings output should normalize:

- next report date.
- announcement timing when available.
- fiscal quarter/year.
- EPS estimate and revenue estimate when available.
- most recent actual EPS/revenue when available.
- recent surprise history.
- source, captured timestamp, freshness, and missing-field warnings.

News primary path:

- Finnhub company-news in the base MVP path, capped, sorted, and deduplicated before LLM use.

News fallback path:

- Alpha Vantage `NEWS_SENTIMENT` filtered by ticker, sorted latest, with a bounded limit for quota control when enabled. Sentiment fields are metadata only, not conclusions.
- If both providers fail or return no items, continue only if minimum evidence still passes and show an explicit no-news or news-unavailable warning.

News output should normalize:

- published timestamp.
- source.
- headline.
- summary.
- URL.
- related ticker.
- provider sentiment fields when present, treated as metadata only.
- source, captured timestamp, freshness, and missing-field warnings.

Provider adapters should include tests for Alpha Vantage earnings/news responses, Finnhub fallback responses, empty-result responses, quota/rate-limit responses, and malformed payloads.

## Evidence Citations

Velox should use tool/evidence citations rather than document-chunk citations. Every normalized evidence item receives a stable evidence ID for the current run, such as `E1`, `E2`, and `E3`.

Evidence IDs should be assigned after evidence assembly and carried into all LLM prompts. The final report can cite claims with these IDs, for example:

- `The next expected earnings event is listed for October 29, 2026 after market close. [E1]`
- `Recent headlines center on margin pressure and AI infrastructure spending. [E4, E7, E9]`

Each evidence record should include:

- evidence ID.
- source type: earnings, SEC filing, company fact, news, quote, or prior report.
- provider/tool name.
- source URL when available.
- source title or field name.
- published/reported date when available.
- captured timestamp.
- freshness.
- normalized data payload.

The final brief should include a Sources table mapping evidence IDs to provider, source, date, title/field, and URL. The reviewer should fail or request revision when key claims lack citations, cite missing evidence IDs, or cite evidence that does not support the claim.

## Local Ticker Lookup

Ticker lookup is a local static data dependency so the UI stays fast and the app does not spend remote API quota on every keystroke.

Recommended source:

- SEC file: `https://www.sec.gov/files/company_tickers_exchange.json`
- Fields from source: CIK, company name, ticker, exchange.
- Normalized project file: `data/static/company_tickers.json`.
- Runtime fields: `ticker`, `company_name`, `exchange`, `cik`.

This is preferable to a Russell 1000-only cache for the MVP because the SEC file is small, public, official, no-key, and covers far more U.S. public-company symbols. The UI can still optionally filter to major exchanges such as Nasdaq and NYSE, but the underlying cache should not be artificially limited to one index.

The project should include a refresh script that downloads the SEC ticker file, normalizes it, writes source metadata and captured timestamp, and can be run manually before submission.

## State Model

The graph state should include:

- selected ticker and company identity.
- run ID and timestamps.
- user-facing progress text.
- tool-call records.
- evidence tables.
- missing fields and stale-data flags.
- retry/fallback records.
- prior memory and delta findings.
- generated brief sections.
- reviewer findings.
- approval status.
- telemetry.

## Tool Result Contract

Every tool should return a structured result:

| Field | Purpose |
|---|---|
| `tool_name` | Stable tool identifier. |
| `status` | `success`, `failed`, `retried`, `fallback_used`, or `skipped`. |
| `failure_category` | `none`, `recoverable`, `degraded_continuable`, or `non_recoverable`. |
| `started_at` / `ended_at` | Timing and freshness audit. |
| `duration_ms` | Tool latency. |
| `source` | MCP server, API endpoint, local snapshot, or memory store. |
| `freshness` | Current, stale, unknown, or not applicable. |
| `fallback_used` | Whether fallback data was used. |
| `fallback_reason` | Why fallback was needed. |
| `data` | Normalized output payload. |
| `error` | Human-readable error, if any. |

Silent fallback is not allowed. If saved report data is reused because a live tool failed, the tool result must include the original report timestamp and the final brief must show a stale-data warning.

## Failure Taxonomy

Every failed tool or agent step should be categorized so the orchestrator can choose the right behavior and the UI can explain what is happening.

| Category | Meaning | Orchestrator behavior | User-facing behavior |
|---|---|---|---|
| `recoverable` | Temporary failure that may succeed with retry, such as timeout, 429, transient network issue, or LLM schema miss. | Retry once, then fallback if configured. | Show active progress such as `Retrying news fetch...` or `Retrying reviewer with fallback model...`. |
| `degraded_continuable` | Step failed or returned partial/empty data, but the report can still be useful if the gap is disclosed. | Continue if minimum evidence gate passes; carry warning into evidence pack, report, reviewer, and telemetry. | Show `News unavailable; continuing with SEC and earnings evidence.` |
| `non_recoverable` | The run cannot safely continue, such as unresolved company identity, missing minimum evidence, invalid final schema after retry, or safety violation. | Interrupt or stop before producing/saving a report. | Show a clear stop reason and next action. |

Common cases:

| Case | Category | Expected handling |
|---|---|---|
| Alpha Vantage timeout | `recoverable` | Retry once; use Finnhub fallback when configured; otherwise degrade if minimum evidence passes. |
| Alpha Vantage quota/rate limit | `recoverable` then `degraded_continuable` | Retry only if appropriate; otherwise fallback or continue with warning. |
| Empty news result | `degraded_continuable` | Continue with `no recent news found` or `news unavailable` warning. |
| SEC company identity missing | `non_recoverable` | Ask user to reselect ticker or stop. |
| SEC recent filings unavailable but identity exists | `degraded_continuable` | Continue if earnings/news/company identity are sufficient; disclose gap. |
| No prior Mem0 report exists | None | Continue with `prior_report_status=missing`; do not show this as a failure. |
| Mem0 lookup failure | `degraded_continuable` | Continue with `prior_report_status=lookup_failed`; do not claim no prior report exists. |
| Optional analysis LLM schema failure | `recoverable` then `degraded_continuable` | Retry once; if exhausted, continue without generated themes/delta/risks and disclose the gap. |
| Brief/reviewer LLM schema failure | `recoverable` then `non_recoverable` | Retry once; if exhausted, stop before approval or memory save. |
| Reviewer citation metadata mismatch | `recoverable` | Deterministically repair section `citation_ids`, rerun reviewer once, then either continue or stop with findings. |
| Reviewer safety or unsupported-claim failure | `non_recoverable` until fixed | Stop with reviewer findings; do not save memory. |

## Loading and Progress States

Each LangGraph node should publish user-facing progress text, for example:

- Finding matching U.S. tickers.
- Checking company identity and SEC mapping.
- Looking up the earnings calendar.
- Pulling recent company context.
- Reading prior saved memory.
- No prior approved report memory found.
- Comparing current findings with the last saved report.
- Retrying news fetch after a timeout.
- Continuing without recent news because the provider returned no articles.
- Continuing without prior report memory because Mem0 lookup failed.
- Stopping before draft because minimum evidence was not met.
- Reviewing the brief for unsupported claims.
- Waiting for approval before saving.

Progress text should update as the graph advances, and failed or retried steps should be visible in the same timeline. The app should stay alive where the failure is recoverable or degraded-but-continuable, and it should stop clearly when the failure is non-recoverable.

Progress messages should avoid raw exception text. They should state the action and impact in user-facing language, while detailed error metadata stays in the tool ledger.

## Telemetry

Telemetry is collected as part of graph state and displayed at the bottom of the screen after each run.

Telemetry should include:

- Total run time.
- Time by agent/node.
- Time by external tool call.
- Slowest agent or tool call.
- Retry count and fallback count.
- Whether saved report data was used.
- Time spent generating the narrative brief.
- Time spent formatting tables/report sections.
- Memory lookup and memory save duration.
- Final status: completed, completed with warnings, failed, or waiting for approval.

## Spike Measurements

During foundational spikes, Velox should measure cost and latency before investing in polish. The goal is to estimate the happy-path report runtime and the worst-case runtime when retries/fallbacks are triggered.

Measure for each external tool call:

- provider/tool name.
- request count.
- duration.
- status.
- retry count.
- fallback used.
- quota/rate-limit signal when present.

Measure for each LLM call:

- provider/model.
- prompt version.
- input tokens.
- output tokens.
- estimated cost when provider pricing is known.
- duration.
- schema validation status.
- retry/fallback count.

Spike scenarios:

- Happy path for 2-3 representative tickers.
- Missing optional provider key.
- Alpha Vantage quota or rate-limit response.
- Empty news response.
- Malformed provider payload.
- LLM schema failure followed by retry or fallback model.
- Mem0 lookup failure.

The spike output should produce a short local measurement summary with estimated total report time, slowest step, external request count, LLM token/cost estimate, and worst-case retry path. The UI telemetry should later reuse the same timing fields.

## Data Presentation

Velox should display evidence in structured tables before asking the user to read narrative output. Use Streamlit dataframes and column configuration for consistent formatting across:

- Ticker search results: ticker, company name, exchange, type.
- Tool-call log: step, user-facing status, tool, status, retries, duration, source, freshness, fallback used, notes.
- Sources/citations: evidence ID, evidence type, provider, title/field, source date, captured timestamp, URL.
- Earnings snapshot: report date, fiscal quarter, EPS estimate, revenue estimate, prior actuals, announcement timing.
- Company context: sector, industry, market context, latest filing, source.
- Recent developments: date, source, theme, headline, relevance.
- Risk register: risk, severity, evidence, source.
- Delta from prior memory: field, previous, current, changed, note.
- Reviewer findings: check, status, issue, recommendation.
- Telemetry summary: agent/tool, duration, retries, fallback used, status.

The final brief should be concise and readable, with tables for facts and short narrative sections for interpretation.

## Analyst-Style Report Output

The final output should feel like an analyst-style earnings brief, not a long generated essay. The strongest MVP report is a clean research packet with cited analysis layered on top: deterministic tables/charts for facts, short LLM-written narrative for interpretation, and explicit missing-data notes.

Recommended report sections:

| Section | Preferred presentation | Evidence needed |
|---|---|---|
| Header / Company Snapshot | Compact metric strip plus table | ticker, company name, exchange, sector, latest price when available |
| Earnings Setup | Table | next earnings date, announcement timing, fiscal quarter/year, EPS/revenue estimates, prior actuals |
| Historical Earnings Pattern | Table plus small chart | last 4 quarters EPS actual vs estimate and surprise history |
| Recent Developments | Themed table | news date, source, headline, theme, earnings relevance, citation IDs |
| What Changed Since Last Report | Delta table | prior approved report vs current evidence |
| Risk Register | Table with severity labels | evidence-backed risks, severity, rationale, citations |
| Earnings Call Watch Items | Short checklist/table | questions or topics derived from evidence |
| Missing / Stale Data Notes | Warning table | failed tools, stale fallback, missing fields, no-news result |
| Sources | Citation table | evidence IDs, provider, source date, title/field, URL |
| Telemetry | Collapsed technical table | node/tool timings, retries, fallbacks, final status |

Recommended visualizations:

- EPS actual vs estimate chart for recent quarters when historical earnings data is available.
- Revenue actual vs estimate chart when revenue fields are available.
- News theme count bar chart based on classified recent developments.
- Timeline of recent news, latest filing, and upcoming earnings date when dates are available.
- Risk severity table using labels or color-coded cells rather than unsupported quantitative scoring.

Avoid valuation charts, price targets, or prediction-heavy visuals in the MVP unless the underlying assumptions are explicit and the reviewer confirms they do not cross into personalized investment advice.

Report quality depends on evidence coverage. SEC identity, CIK, exchange, filing metadata, and company facts should be high-confidence. Earnings dates/history should be medium-high but provider-dependent. Estimates and revenue fields may be missing. News coverage is medium-confidence and should be treated as evidence for themes, not definitive truth. Quote data on free tiers may be delayed or end-of-day.

To keep output quality consistent, factual sections should be rendered deterministically from the evidence pack, while LLMs should handle only interpretive sections such as news themes, risk explanations, watch items, delta summaries, and the final narrative. The reviewer should check that generated claims cite valid evidence and that missing data is disclosed.

## Environment Variables

Required:

- `MEM0_API_KEY`
- At least one LLM provider key: `NEBIUS_API_KEY` or `FIREWORKS_API_KEY`
- `ALPHA_VANTAGE_API_KEY` for primary earnings/news data
- `SEC_USER_AGENT` for SEC API requests

Optional:

- Additional LLM provider keys for showing different models across agents.
- `FINNHUB_API_KEY` for richer earnings/news fallback coverage.

## Safety Boundaries

- Do not use Kubera.
- Do not use personal finance, brokerage, portfolio, bank, or account data.
- Do not place trades or produce personalized investment advice.
- Do not hide missing, stale, failed, or fallback data.

## Fail-Fast Build Order

Build the app in an order that validates foundational blocks before UI polish or optional provider breadth.

| Step | Happy path to prove | Failure/recovery to prove |
|---|---|---|
| 1. Data spike | Local ticker lookup works; Alpha Vantage returns earnings/news; SEC returns company context for 2-3 tickers; cost/latency measurements are captured. | Missing key, quota/rate-limit response, empty news, malformed response, unsupported ticker, and measured worst-case retry/fallback timing. |
| 2. Typed contracts | `RunState`, `ToolResult`, `EvidencePack`, `EarningsSnapshot`, `NewsItem`, and citation records are populated. | Failed tools produce structured records instead of uncaught exceptions or silent gaps. |
| 3. Provider adapters | SEC, Alpha Vantage, and optional Finnhub adapters normalize data into one evidence pack. | Retry once, fallback when configured, otherwise record explicit warning. |
| 4. Minimal LangGraph flow | Parallel evidence collection reaches evidence pack and minimum evidence gate. | Weak evidence stops before drafting with a clear user-facing explanation. |
| 5. LLM structured-output spike | News themes and delta run in parallel; risk uses both; draft and review produce valid schemas. | Schema/grounding failure triggers retry/fallback; exhausted failure interrupts visibly. |
| 6. Mem0 memory | Prior report lookup, delta, approved upsert save, and local JSON mirror work for one ticker. | Mem0 lookup failure is marked `lookup_failed`; save failure is visible; no duplicate version per ticker/CIK. |
| 7. Streamlit UI | Local typeahead, progress timeline, evidence tables, cited report, reviewer findings, and approval button work. | Warnings, retries, stale/missing data, and memory failures are visible in the UI. |
| 8. Tests and demo path | Known tickers produce useful reports with citations and telemetry. | Intentional failure path proves no silent fallback and reviewer catches unsupported claims. |
| 9. Polish and submission | Sample briefs, final writeup, Mermaid exports, and demo video are ready. | All reviewer-facing `TODO:` items are resolved or removed. |
