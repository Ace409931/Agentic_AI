"""
Trace builder: converts the LangGraph message list into structured TraceEvent objects.

Design contract (from §6 of the spec):
- Walk messages in order; emit one event per message.
- HumanMessage   → type: "user_request"
- AIMessage with tool_calls → one "agent_decision" + one "tool_call" per pending call
- ToolMessage    → type: "tool_result"
- Final AIMessage (no tool_calls) → type: "final_answer"

No raw model chain-of-thought text is exposed — only structured facts
(tool name, args, results) and templated one-line explanations.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .models import TraceEvent

# ---------------------------------------------------------------------------
# Templated one-line agent-decision descriptions, keyed by tool name.
# These are looked up (not generated) so nothing is invented per-request.
# ---------------------------------------------------------------------------
_DECISION_TEMPLATES: dict[str, str] = {
    "convert_currency": (
        "Currencies differ — the model decided a currency conversion is required before comparison."
    ),
    "check_budget_feasibility": (
        "Converted cost received — a budget comparison is required to determine feasibility."
    ),
}
_DEFAULT_DECISION = "The model decided to use a tool to continue reasoning."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_call_args(tc: Any) -> dict[str, Any]:
    """Normalise tool_call args across different LangChain versions."""
    if isinstance(tc, dict):
        return tc.get("args", tc.get("arguments", {}))
    return getattr(tc, "args", {}) or {}


def _tool_call_name(tc: Any) -> str:
    if isinstance(tc, dict):
        return tc.get("name", "")
    return getattr(tc, "name", "")


def build_trace(messages: list) -> list[TraceEvent]:
    """
    Walk the LangGraph agent message list and emit structured TraceEvents.

    Args:
        messages: The ``messages`` list from the LangGraph state returned by invoke().

    Returns:
        A list of TraceEvent objects representing the full agent reasoning chain.
    """
    events: list[TraceEvent] = []

    for msg in messages:
        # ── User request ─────────────────────────────────────────────────────
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            step = len(events) + 1
            events.append(
                TraceEvent(
                    step=step,
                    type="user_request",
                    title="User Query",
                    description=content[:300],  # trim very long queries for display
                    tool=None,
                    arguments=None,
                    result=None,
                    timestamp=_now(),
                    status="complete",
                )
            )

        # ── AI message ────────────────────────────────────────────────────────
        elif isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", []) or []

            if tool_calls:
                # Emit agent_decision + tool_call pair for each pending tool call
                for tc in tool_calls:
                    name = _tool_call_name(tc)
                    args = _tool_call_args(tc)
                    description = _DECISION_TEMPLATES.get(name, _DEFAULT_DECISION)

                    # Agent decision event (the key autonomous-reasoning signal)
                    step = len(events) + 1
                    events.append(
                        TraceEvent(
                            step=step,
                            type="agent_decision",
                            title="Agent selected next tool",
                            description=description,
                            tool=name,
                            arguments=args,
                            result=None,
                            timestamp=_now(),
                            status="complete",
                        )
                    )

                    # Tool call event (the actual invocation record)
                    step = len(events) + 1
                    events.append(
                        TraceEvent(
                            step=step,
                            type="tool_call",
                            title=f"Calling tool: {name}",
                            description=f"Invoking {name} with the provided arguments.",
                            tool=name,
                            arguments=args,
                            result=None,
                            timestamp=_now(),
                            status="complete",
                        )
                    )
            else:
                # Final AI message with no tool_calls
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                step = len(events) + 1
                events.append(
                    TraceEvent(
                        step=step,
                        type="final_answer",
                        title="Agent Final Answer",
                        description=content,
                        tool=None,
                        arguments=None,
                        result=None,
                        timestamp=_now(),
                        status="complete",
                    )
                )

        # ── Tool result ────────────────────────────────────────────────────────
        elif isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            tool_name = getattr(msg, "name", None) or "tool"
            step = len(events) + 1
            events.append(
                TraceEvent(
                    step=step,
                    type="tool_result",
                    title=f"Result: {tool_name}",
                    description=content,
                    tool=tool_name,
                    arguments=None,
                    result=content,
                    timestamp=_now(),
                    status="complete",
                )
            )

    return events


# ---------------------------------------------------------------------------
# Structured data extraction
# Parses feasibility, numbers, and currency from the tool_result events
# rather than post-processing the LLM's free-text final answer.
# ---------------------------------------------------------------------------

_FEASIBLE_RE = re.compile(r"Trip is feasible", re.IGNORECASE)
_NOT_FEASIBLE_RE = re.compile(r"Trip is NOT feasible", re.IGNORECASE)
_TOTAL_COST_RE = re.compile(r"Total cost is ([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_BUDGET_RE = re.compile(r"the budget is ([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_REMAINING_RE = re.compile(r"Remaining budget: ([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_OVERAGE_RE = re.compile(r"Over budget by ([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_CONVERTED_RE = re.compile(
    r"Converted [0-9.]+ \w+ to ([0-9]+(?:\.[0-9]+)?) (\w+)", re.IGNORECASE
)
_FEASIBILITY_VALUES_RE = re.compile(
    r"Total cost is ([0-9]+(?:\.[0-9]+)?) ([A-Z]{3}).*?"
    r"budget is ([0-9]+(?:\.[0-9]+)?) ([A-Z]{3})",
    re.IGNORECASE,
)


def extract_structured_data(
    trace: list[TraceEvent],
) -> dict[str, Any]:
    """
    Walk trace events and extract feasible, total_cost, budget, currency
    from the tool_result events (not from the LLM's free-text answer).

    Returns a dict with keys: feasible, total_cost, budget, currency.
    Values are None if not found.
    """
    result: dict[str, Any] = {
        "feasible": None,
        "total_cost": None,
        "budget": None,
        "currency": None,
        "remaining": None,
        "overage": None,
    }

    converted_amount: float | None = None
    converted_currency: str | None = None

    for event in trace:
        if event.type != "tool_result" or not event.result:
            continue

        text = event.result

        # Extract conversion result
        m = _CONVERTED_RE.search(text)
        if m:
            converted_amount = float(m.group(1))
            converted_currency = m.group(2).upper()

        # Extract feasibility
        if _FEASIBLE_RE.search(text) and not _NOT_FEASIBLE_RE.search(text):
            result["feasible"] = True
        elif _NOT_FEASIBLE_RE.search(text):
            result["feasible"] = False

        # Extract cost and budget numbers
        m_cost = _TOTAL_COST_RE.search(text)
        if m_cost:
            result["total_cost"] = float(m_cost.group(1))

        m_budget = _BUDGET_RE.search(text)
        if m_budget:
            result["budget"] = float(m_budget.group(1))

        m_remaining = _REMAINING_RE.search(text)
        if m_remaining:
            result["remaining"] = float(m_remaining.group(1))

        m_overage = _OVERAGE_RE.search(text)
        if m_overage:
            result["overage"] = float(m_overage.group(1))

        m_values = _FEASIBILITY_VALUES_RE.search(text)
        if m_values:
            result["total_cost"] = float(m_values.group(1))
            result["currency"] = m_values.group(2).upper()
            result["budget"] = float(m_values.group(3))

    # Use converted amount as cost if not extracted directly
    if result["total_cost"] is None and converted_amount is not None:
        result["total_cost"] = converted_amount

    if result["currency"] is None and converted_currency is not None:
        result["currency"] = converted_currency

    return result
