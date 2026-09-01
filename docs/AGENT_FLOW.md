# Agent Flow: Velox Earnings Research Run

The editable Mermaid source for this flow is kept as a local-only working file under `docs/local/`. The reviewer-facing workflow image lives in [velox-agentic-workflow.jpeg](../assets/velox-agentic-workflow.jpeg).

This flow focuses on the runtime path from ticker selection to reviewed report production. It highlights state updates, tool retries, degraded continuation, reviewer repair/revision loops, interrupts, and the Human Review Gate.

## Runtime Sequence

1. User selects a ticker from local typeahead.
2. Velox initializes `RunState`.
3. The graph resolves company identity from the local SEC-seeded ticker cache.
4. Prior approved report memory is loaded from Mem0/local snapshot when available.
5. Public evidence is collected from SEC, Finnhub, and optionally Alpha Vantage.
6. Provider failures are categorized, retried once when recoverable, and either sent through fallback or disclosed as gaps.
7. Evidence is normalized into a cited evidence pack.
8. The minimum evidence gate stops weak runs before drafting.
9. LLM agents produce news themes, delta findings, risks/watch items, and the draft brief using structured JSON.
10. The reviewer checks citations, warning disclosure, schema, stale-data handling, unsupported claims, and safety boundaries.
11. Repairable citation issues or content issues are routed through one automatic repair/revision attempt.
12. If the reviewer passes, the run waits at the Human Review Gate.
13. If the user approves, Velox saves the report to Mem0 and a local snapshot mirror. If the user does not approve, the run ends without a write action.

## Agent Nodes

| Node | Responsibility | LLM? | State written |
|---|---|---:|---|
| Resolve company identity | Confirms the selected ticker maps to a public company, exchange, and CIK. | No | `company`, `warnings`, `status` |
| Prior report lookup | Loads the last approved report snapshot when one exists and distinguishes missing memory from lookup failure. | No | `prior_memory`, `tool_results`, `warnings` |
| Evidence collection | Calls public data providers and records tool status, retry/fallback behavior, freshness, and raw normalized payloads. | No | `tool_results`, `retry_records`, `fallback_records` |
| Evidence assembler | Normalizes provider outputs into cited earnings, SEC, news, and prior-memory evidence. | No | `evidence_pack`, `earnings`, `news`, `warnings` |
| Minimum evidence gate | Stops before drafting when evidence is too weak to support a grounded brief. | No | `status`, `progress_text`, `warnings` |
| News Theme Agent | Groups recent headlines into earnings-relevant themes using only supplied evidence. | Yes | `news_themes`, `warnings`, `telemetry` |
| Delta Agent | Compares current evidence against prior approved memory when available. | Yes | `delta_findings`, `warnings`, `telemetry` |
| Risk Analyst Agent | Produces earnings-relevant risks and watch items from the evidence, themes, and delta findings. | Yes | `risk_findings`, `warnings`, `telemetry` |
| Brief Drafter Agent | Creates the structured cited earnings preview brief. | Yes | `brief`, `warnings`, `telemetry` |
| Reviewer Agent | Checks schema, citations, warning disclosure, stale-data handling, unsupported claims, and no-investment-advice boundaries. | Yes/checklist | `reviewer_result`, `approval_status`, `telemetry` |
| Human Review Gate | Pauses before durable memory writes. | Human | `approval_status` |
| Memory save | Saves only approved reports to Mem0 and local snapshot mirror. | No | `prior_memory`, `tool_results`, `approval_status` |

## Interrupts And Awaits

| Point | Type | Why it exists |
|---|---|---|
| Unresolvable ticker selection | Interrupt | Typeahead prevents most invalid tickers, but this catches stale local data or unsupported symbols. |
| Tool failure after retry | Branch | Continue with explicit missing-data/stale-data warnings instead of silent fallback. |
| Minimum evidence missing | Interrupt | Stop before drafting if the report would be too weak to ground. |
| Optional analysis output failure | Degraded continuation | News themes, delta, or risks can be skipped with visible warnings if the rest of the report remains grounded. |
| Draft/reviewer output failure | Interrupt | Stop before approval if final report or reviewer output cannot be validated. |
| Reviewer failed | Repair/revision loop | Attempt deterministic citation repair or one content revision before blocking approval. |
| Human approval | Await | The agent can research and draft autonomously, but Mem0/local snapshot writes require explicit approval. |

## Model Pins

The submitted configuration pins each LLM-backed node to a specific provider/model/prompt version so demo behavior is reproducible while still allowing `.env` overrides.

| Stage | Default model |
|---|---|
| News theme analysis | `accounts/fireworks/models/gpt-oss-120b` |
| Delta analysis | `openai/gpt-oss-120b` |
| Risk analysis | `accounts/fireworks/models/gpt-oss-120b` |
| Brief drafting | `accounts/fireworks/models/gpt-oss-120b` |
| Reviewer | `openai/gpt-oss-120b` |

Prompt files:

- `src/velox/prompts/news_theme.md`
- `src/velox/prompts/delta.md`
- `src/velox/prompts/risk.md`
- `src/velox/prompts/brief_drafter.md`
- `src/velox/prompts/reviewer.md`
