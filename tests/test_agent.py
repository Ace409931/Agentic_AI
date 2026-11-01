"""
Integration tests for the Travel Budget Planner agent.
These tests require Ollama running with qwen2.5:3b pulled.

Run with:
  pytest tests/test_agent.py -v -m integration

Skip in CI without Ollama:
  pytest tests/test_agent.py -v -m "not integration"
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def is_ollama_available() -> bool:
    """Check if Ollama server is running and qwen2.5:3b is available."""
    try:
        import httpx
        from backend.config import OLLAMA_HOST, OLLAMA_MODEL
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False
        models = [m.get("name", "") for m in r.json().get("models", [])]
        return OLLAMA_MODEL in models
    except Exception:
        return False


requires_ollama = pytest.mark.skipif(
    not is_ollama_available(),
    reason="Ollama service is not reachable or the configured model is missing",
)


@pytest.fixture(scope="module")
def agent_runner():
    """Import and return the run_agent function (deferred so no Ollama at collection time)."""
    from backend.agent import run_agent
    return run_agent


@pytest.fixture(scope="module")
def trace_builder():
    from backend.tracing import build_trace, extract_structured_data
    return build_trace, extract_structured_data


@pytest.mark.integration
@requires_ollama
def test_feasible_query_end_to_end(agent_runner, trace_builder):
    """
    Feasible query: ₹100,000 budget, €900 trip cost.
    Expected: feasible: True, convert_currency called before check_budget_feasibility.
    """
    build_trace, extract_structured_data = trace_builder
    query = "I have a budget of 100000 INR and my estimated trip cost is 900 EUR. Can I afford it?"

    messages = agent_runner(query)
    trace = build_trace(messages)
    structured = extract_structured_data(trace)

    # Must be feasible
    assert structured["feasible"] is True, f"Expected feasible=True, got {structured}"

    # Both tools must appear in the trace, in the correct order
    tool_calls = [e.tool for e in trace if e.type == "tool_call"]
    assert "convert_currency" in tool_calls, "convert_currency must be in trace"
    assert "check_budget_feasibility" in tool_calls, "check_budget_feasibility must be in trace"
    assert tool_calls.index("convert_currency") < tool_calls.index(
        "check_budget_feasibility"
    ), "convert_currency must be called before check_budget_feasibility"


@pytest.mark.integration
@requires_ollama
def test_not_feasible_query_end_to_end(agent_runner, trace_builder):
    """
    Non-feasible query: ₹50,000 budget, €900 trip cost.
    Expected: feasible: False, correct overage in trace.
    """
    build_trace, extract_structured_data = trace_builder
    query = "I have a budget of 50000 INR and my estimated trip cost is 900 EUR. Can I afford it?"

    messages = agent_runner(query)
    trace = build_trace(messages)
    structured = extract_structured_data(trace)

    assert structured["feasible"] is False, f"Expected feasible=False, got {structured}"

    # Overage should appear in a tool_result
    tool_results = [e.result for e in trace if e.type == "tool_result" and e.result]
    combined = " ".join(tool_results)
    assert "35500" in combined, f"Expected overage 35500 in results. Got: {combined}"


@pytest.mark.integration
@requires_ollama
def test_trace_contains_agent_decision_events(agent_runner, trace_builder):
    """The trace must contain agent_decision events (proving autonomous tool selection)."""
    build_trace, _ = trace_builder
    query = "I have a budget of 100000 INR and my estimated trip cost is 900 EUR. Can I afford it?"

    messages = agent_runner(query)
    trace = build_trace(messages)

    decision_events = [e for e in trace if e.type == "agent_decision"]
    assert len(decision_events) >= 1, "Trace must contain at least one agent_decision event"


@pytest.mark.integration
@requires_ollama
def test_same_currency_no_conversion_needed(agent_runner, trace_builder):
    """When currencies match, the budget should be checked without conversion."""
    build_trace, extract_structured_data = trace_builder
    query = "I have a budget of 100000 INR and my estimated trip cost is 80000 INR. Can I afford it?"

    messages = agent_runner(query)
    trace = build_trace(messages)
    structured = extract_structured_data(trace)

    assert structured["feasible"] is True
    tool_calls = [event.tool for event in trace if event.type == "tool_call"]
    assert "check_budget_feasibility" in tool_calls
    assert "convert_currency" not in tool_calls
