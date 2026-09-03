# PRD: Velox Week 3 Stock Earnings Research Agent

## Primer

My agent helps individual investors prepare for upcoming earnings in a web app, replacing the 1-2 hours of manual searching across earnings calendars, SEC filings, financial data sites, news, and analyst commentary. It researches a ticker on its own using ticker-search, earnings-calendar, SEC/company-facts, market-data, news, Mem0 memory, and LLM tools, hands off to the investor before saving or treating any output as an investment decision, and I will know it works when a user can typically generate a useful, source-grounded earnings preview brief in under 3 minutes for supported U.S. tickers, with a 5-minute ceiling for retry/fallback runs, visible tool usage, clear missing-data notes, and no unsupported investment recommendations.

## One-Liner

Velox is a multi-step earnings research agent that lets a user search for a U.S. public-company ticker and generate a reviewed earnings preview brief with visible tool usage, source labels, risk flags, missing-data notes, and a what-changed-since-last-time update from prior approved memory.

## Objective

Build a lean Week 3 agentic AI system that helps individual investors prepare for public-company earnings events. The product must make the agent's control flow, state, tool use, failure handling, memory, and human approval boundary visible to the user.

Velox is a learning prototype. It is not a brokerage, advisor, trading system, portfolio manager, or personalized financial advice product.

## Framework

| Field | Decision |
|---|---|
| Agent goal | Generate a source-grounded earnings preview brief for a public company ticker, including earnings timing, recent performance context, news themes, risks, and questions to watch. |
| Where do people use it? | A web app where the user searches for a U.S. ticker with typeahead, selects a company, sees plain-language agent progress and tool calls, reviews the draft brief, and approves saving memory. |
| What steps does it take, in order? | 1. Select a ticker from local typeahead, resolve company identity, and create a research plan. 2. Fetch earnings/calendar data, basic company facts, recent market context, and recent news. 3. Retrieve prior memory and analyze expectations, risks, and changes since the last saved brief. 4. Draft a structured earnings preview. 5. Run a reviewer pass and ask the human to approve saving. |
| What can it actually do? | Search U.S. ticker symbols locally, look up public earnings data, retrieve public company facts or recent filing metadata, fetch recent market/company context, search or ingest recent news headlines, compare against prior memory, and save approved report memory. External research is read-only; saving final memory requires human approval. |
| What does it need to remember? | It remembers up to 10 saved ticker reports, including ticker, company, report timestamp, key thesis, risks, watch items, sources, and missing-data notes. Saved memory should be bounded, timestamped, reviewable, and clearable by the user. |
| What should it never do? | It should never place trades, give definitive buy/sell instructions, guarantee earnings outcomes, hide missing data, fabricate citations, access personal finance accounts, or present educational research as personalized financial advice. |
| Human-in-the-loop | The app ends each successful run at a Human Review Gate. The user reviews the brief, sources, warnings, and reviewer findings before approving memory save. The user can approve, reject by doing nothing, or rerun with a revised ticker; write actions do not happen automatically. |
| What happens when something breaks? | If a tool fails, the agent retries once, falls back to a simpler source or saved report data when available, and clearly marks the missing or stale field in both the UI and the brief. If ticker validation fails, it stops and asks for a corrected ticker. |
| How do you know it worked? | It produces usable earnings preview briefs for supported U.S. tickers, typically in under 3 minutes and within 5 minutes for retry/fallback runs, includes source labels/links and risk flags, shows missing-data warnings when needed, and avoids unsupported investment recommendations. |

## User Experience Requirements

Velox does not require a conversational UI. The application uses a focused web form:

1. User types a company name or ticker into a typeahead search box.
2. Search results show ticker on the left and company name on the right.
3. User selects one result and starts the research run.
4. The app shows progressive agent status and tool calls while the brief is generated.
5. The app displays structured tables for facts, tool usage, risks, changes, and reviewer findings.
6. The user can inspect run telemetry showing which agents and tools took the most time.
7. The user can inspect an Evals view that separates report-quality assessment from deterministic guardrail checks.
8. The user reviews the final brief, reviewer warnings, missing-data notes, and delta section.
9. The user approves saving the result to memory and a local report snapshot.
10. If the user has already saved 10 tickers, the memory layer blocks additional new-company saves until older saved records are cleared outside the main run path.

The app should be shippable from GitHub. A reviewer should be able to copy `.env.example` to `.env`, add API keys, install dependencies, and run the app locally. Missing optional keys should degrade gracefully with clear UI warnings rather than blocking the entire application.

## Agentic System Requirements

Velox is designed to make the hard parts of agentic systems visible in both the code and the demo.

| Requirement | Product Requirement | Demo Evidence |
|---|---|---|
| Control flow | The product must show the agent moving through a multi-step research workflow rather than returning one opaque response. | The UI shows each step as completed, skipped, retried, failed, or waiting for approval. |
| State | The product must carry structured state across steps, including selected ticker, evidence, tool results, memory, draft brief, reviewer findings, missing fields, and approval status. | The final brief and tool log show how earlier steps affect later sections, especially delta and missing-data sections. |
| Tool failure | The product must handle failed tools explicitly. Silent fallback is not allowed. | The demo includes one intentional failure path and shows missing-data or stale-data warnings. |
| Human boundary | The product may research, analyze, draft, and review autonomously, but durable write actions require human approval. | The UI shows a Human Review Gate and pauses before saving Mem0 memory or writing a report snapshot. |

## Memory Requirements

Velox stores only project-owned earnings reports that the user explicitly approves. Each saved report includes the ticker, company name, report timestamp, source timestamps, thesis summary, risk summary, watch items, missing-data notes, and reviewer status.

The application stores up to 10 tickers in memory. When the limit is reached, Velox prevents additional new-company saves and surfaces the limit clearly rather than silently overwriting an existing memory.

Saved reports support delta analysis against the last approved report. Saved report data must never be presented as fresh data. If a future version uses saved reports as fallback evidence because a live tool failed or returned no result, Velox must label the original report timestamp and include a stale-data warning in the tool log and final brief.

## Data and Safety Boundaries

In scope:

- Public tickers and public company information.
- Public/free APIs where possible.
- Project-owned local report snapshots.
- Project-owned report memories created by the app after human approval.
- Educational earnings research and source-grounded summaries.

Out of scope:

- Kubera or any personal finance connector.
- Brokerage, portfolio, bank, or account integrations.
- Private portfolio holdings, account balances, transactions, or personal user data.
- Trade placement, buy/sell instructions, suitability analysis, guarantees, or personalized financial advice.

## Final Brief Requirements

Each generated brief should include:

- Ticker and company identity.
- Earnings timing and available expectation fields.
- Recent company/market context.
- Recent news themes.
- Key risks and watch items.
- Bull case and bear case, framed as considerations rather than advice.
- What changed since the last approved report, when available.
- Missing-data and source-freshness notes.
- Stale-data notes when saved report data is reused because a live tool failed.
- Reviewer warnings.
- Educational disclaimer.

## Success Criteria

- Submission demo runs end to end for 2-3 public tickers.
- Each brief is generated in under 3 minutes on typical supported runs, with a 5-minute ceiling for runs that trigger provider retry/fallback paths.
- UI clearly shows multi-step agent progress, plain-language loading states, and tool usage.
- Telemetry shows total runtime, slowest step, per-agent timing, per-tool timing, retries, and fallbacks.
- Saved project-owned reports power a visible what-changed-since-last-time section.
- Tool failures produce graceful missing-data or stale-data notes rather than crashes, hallucinations, or silent fallbacks.
- Reviewer catches unsupported claims or safety-boundary issues.
- Final output remains educational and never gives direct trading instructions.

## Future Enhancements

These are intentionally out of the submission MVP but are documented because they are natural next steps for a stronger production agent:

- Run independent provider calls concurrently, and run news-theme and delta analysis concurrently before risk analysis.
- Add durable graph checkpoint/resume for interrupted runs beyond the current state preservation and idempotent save safeguards.
- Add timeout and run-budget telemetry for cancelled or skipped nodes.
- Add an in-app clear-old-reports flow for managing the 10-company saved-memory cap.
- Add saved-report fallback evidence with explicit stale-data labels and original report timestamps.
- Add hosted LangSmith datasets and broader trajectory regression suites.

## Submission Deliverables

- Google Doc explaining the project overview, data/tools used, prompts or AI coding workflow, iterations tried, and learnings.
- Demo video of 5 minutes or less showing the app running live.
- GitHub repository or code bundle containing the implementation, README, PRD, and architecture document.
