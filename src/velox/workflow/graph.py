"""LangGraph assembly for Velox."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from velox.config import AppSettings
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import RunTelemetry
from velox.observability import build_run_metadata, traceable_step
from velox.workflow import progress
from velox.workflow.nodes import (
    make_brief_drafter_node,
    make_collect_evidence_node,
    make_delta_node,
    make_load_memory_node,
    make_news_theme_node,
    make_reviewer_node,
    make_risk_node,
    minimum_evidence_gate_node,
    resolve_company_identity_node,
)


def build_minimal_graph(settings: AppSettings):
    graph = StateGraph(RunState)
    graph.add_node("resolve_company_identity", _traced_node("resolve_company_identity", resolve_company_identity_node, settings))
    graph.add_node("load_memory", _traced_node("load_memory", make_load_memory_node(settings), settings))
    graph.add_node("collect_evidence", _traced_node("collect_evidence", make_collect_evidence_node(settings), settings))
    graph.add_node(
        "minimum_evidence_gate",
        _traced_node("minimum_evidence_gate", minimum_evidence_gate_node, settings, run_type="chain"),
    )

    graph.set_entry_point("resolve_company_identity")
    graph.add_conditional_edges(
        "resolve_company_identity",
        _route_after_stop,
        {"continue": "load_memory", "stop": END},
    )
    graph.add_conditional_edges(
        "load_memory",
        _route_after_stop,
        {"continue": "collect_evidence", "stop": END},
    )
    graph.add_conditional_edges(
        "collect_evidence",
        _route_after_stop,
        {"continue": "minimum_evidence_gate", "stop": END},
    )
    graph.add_edge("minimum_evidence_gate", END)
    return graph.compile()


def build_research_graph(settings: AppSettings):
    graph = StateGraph(RunState)
    graph.add_node("resolve_company_identity", _traced_node("resolve_company_identity", resolve_company_identity_node, settings))
    graph.add_node("load_memory", _traced_node("load_memory", make_load_memory_node(settings), settings))
    graph.add_node("collect_evidence", _traced_node("collect_evidence", make_collect_evidence_node(settings), settings))
    graph.add_node(
        "minimum_evidence_gate",
        _traced_node("minimum_evidence_gate", minimum_evidence_gate_node, settings, run_type="chain"),
    )
    graph.add_node("news_theme_analysis", _traced_node("news_theme_analysis", make_news_theme_node(settings), settings))
    graph.add_node("delta_analysis", _traced_node("delta_analysis", make_delta_node(settings), settings))
    graph.add_node("risk_analysis", _traced_node("risk_analysis", make_risk_node(settings), settings))
    graph.add_node("brief_drafting", _traced_node("brief_drafting", make_brief_drafter_node(settings), settings))
    graph.add_node("review", _traced_node("review", make_reviewer_node(settings), settings))

    graph.set_entry_point("resolve_company_identity")
    graph.add_conditional_edges(
        "resolve_company_identity",
        _route_after_stop,
        {"continue": "load_memory", "stop": END},
    )
    graph.add_conditional_edges(
        "load_memory",
        _route_after_stop,
        {"continue": "collect_evidence", "stop": END},
    )
    graph.add_conditional_edges(
        "collect_evidence",
        _route_after_stop,
        {"continue": "minimum_evidence_gate", "stop": END},
    )
    graph.add_conditional_edges(
        "minimum_evidence_gate",
        _route_after_stop,
        {"continue": "news_theme_analysis", "stop": END},
    )
    graph.add_conditional_edges(
        "news_theme_analysis",
        _route_after_stop,
        {"continue": "delta_analysis", "stop": END},
    )
    graph.add_conditional_edges(
        "delta_analysis",
        _route_after_stop,
        {"continue": "risk_analysis", "stop": END},
    )
    graph.add_conditional_edges(
        "risk_analysis",
        _route_after_stop,
        {"continue": "brief_drafting", "stop": END},
    )
    graph.add_conditional_edges(
        "brief_drafting",
        _route_after_stop,
        {"continue": "review", "stop": END},
    )
    graph.add_edge("review", END)
    return graph.compile()


def initial_state_for_ticker(ticker: str, settings: AppSettings) -> RunState:
    state = RunState(
        selected_ticker=ticker.strip().upper(),
        node_timeout_seconds=settings.node_timeout_seconds,
        run_budget_seconds=settings.run_budget_seconds,
    )
    return state.model_copy(update={"telemetry": RunTelemetry(run_id=state.run_id)})


def invoke_minimal_graph(ticker: str, settings: AppSettings) -> RunState:
    graph = build_minimal_graph(settings)
    initial_state = initial_state_for_ticker(ticker, settings)

    def run_graph() -> dict:
        return graph.invoke(initial_state)

    traced_run = traceable_step(
        name="velox.minimal_graph",
        run_type="chain",
        metadata=build_run_metadata(
            settings=settings,
            run_id=initial_state.run_id,
            ticker=initial_state.selected_ticker,
        ),
        settings=settings,
    )(run_graph)
    output = traced_run()
    return _finalize_state(RunState.model_validate(output))


def invoke_research_graph(ticker: str, settings: AppSettings) -> RunState:
    graph = build_research_graph(settings)
    initial_state = initial_state_for_ticker(ticker, settings)

    def run_graph() -> dict:
        return graph.invoke(initial_state)

    traced_run = traceable_step(
        name="velox.research_graph",
        run_type="chain",
        metadata=build_run_metadata(
            settings=settings,
            run_id=initial_state.run_id,
            ticker=initial_state.selected_ticker,
        ),
        settings=settings,
    )(run_graph)
    output = traced_run()
    return _finalize_state(RunState.model_validate(output))


def stream_research_graph(ticker: str, settings: AppSettings):
    current = initial_state_for_ticker(ticker, settings)
    steps = [
        ("resolve_company_identity", progress.RESOLVING_COMPANY, resolve_company_identity_node),
        ("load_memory", progress.LOADING_MEMORY, make_load_memory_node(settings)),
        ("collect_evidence", progress.COLLECTING_EVIDENCE, make_collect_evidence_node(settings)),
        ("minimum_evidence_gate", progress.ASSEMBLING_EVIDENCE, minimum_evidence_gate_node),
        ("news_theme_analysis", progress.ANALYZING_NEWS, make_news_theme_node(settings)),
        ("delta_analysis", progress.ANALYZING_DELTA, make_delta_node(settings)),
        ("risk_analysis", progress.ANALYZING_RISK, make_risk_node(settings)),
        ("brief_drafting", progress.DRAFTING_BRIEF, make_brief_drafter_node(settings)),
        ("review", progress.REVIEWING_BRIEF, make_reviewer_node(settings)),
    ]

    for name, progress_text, func in steps:
        current = current.touch(progress_text=progress_text, status=RunStatus.RUNNING)
        yield current
        traced_node = _traced_node(name, func, settings)
        current = RunState.model_validate(traced_node(current))
        yield current
        if _route_after_stop(current) == "stop":
            break

    yield _finalize_state(current)


def _traced_node(name: str, func, settings: AppSettings, *, run_type: str = "chain"):
    return traceable_step(
        name=f"node.{name}",
        run_type=run_type,
        metadata={"graph_node": name},
        settings=settings,
    )(func)


def _finalize_state(state: RunState) -> RunState:
    if state.telemetry is None:
        return state
    return state.model_copy(
        update={
            "telemetry": state.telemetry.finish(
                final_status=state.status.value,
                completed_with_warnings=state.completed_with_warnings(),
            )
        }
    )


def _route_after_stop(state: RunState | dict) -> str:
    current = state if isinstance(state, RunState) else RunState.model_validate(state)
    return "stop" if current.status in {RunStatus.STOPPED, RunStatus.FAILED} else "continue"
