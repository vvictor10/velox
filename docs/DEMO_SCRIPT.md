# Velox Demo Script

Target length: under 5 minutes.

## Setup

Use a clean `.env` with Finnhub, SEC, Mem0, one LLM provider, and LangSmith configured. For the main happy-path run, keep:

```bash
ALPHA_VANTAGE_LIVE_ENABLED=true
VELOX_DEMO_FORCE_ALPHA_NEWS_FAILURE=false
```

For the failure demo path, use:

```bash
VELOX_DEMO_FORCE_ALPHA_NEWS_FAILURE=true
```

## Flow

1. Open the app and point out the local ticker search.
2. Select a known supported ticker.
3. Start the run and narrate the progress states as the graph advances.
4. Show the completed report tabs: brief, earnings, developments, risks, sources, and telemetry.
5. Point out citations and warnings.
6. Show the Human Review Gate and approve saving.
7. Rerun the same ticker to show prior approved memory/delta behavior.
8. Run or describe the forced Alpha Vantage news failure path and show that the app retries/falls back visibly.

## Talking Points

- LangGraph controls the multi-step workflow.
- Every tool call uses a shared `ToolResult` contract.
- Failures are categorized and visible.
- LLM agents use curated prompts and structured JSON schemas.
- The reviewer checks citations, warning disclosure, unsupported claims, and investment-advice boundaries.
- Mem0 is used only after human approval.
- LangSmith traces/evals make the workflow inspectable outside the UI.
