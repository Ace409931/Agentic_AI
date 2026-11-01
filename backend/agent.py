"""
LangGraph agent construction for the Travel Budget Planner.

Uses a LangGraph StateGraph with ChatOllama, ToolNode, and conditional
edges to let the model decide when to finish or request another tool.

The loop ends when the model stops requesting tools — that's the model's decision,
not a fixed step count. MAX_ITERATIONS is a defensive safety cap only.
"""

from __future__ import annotations

from typing import Annotated, TypedDict
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages

from .config import OLLAMA_HOST, OLLAMA_MODEL, MAX_ITERATIONS
from .tools import convert_currency, check_budget_feasibility


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    iterations: int


# ---------------------------------------------------------------------------
# System prompt (§5 of the spec).
# Tool order is inferred by the model via clear guidance.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a strict Travel Budget Planner. You must ALWAYS follow these exact rules in order:
1. Identify the trip cost and its currency.
2. Identify the budget and its currency.
3. If the currencies are different, you MUST call the `convert_currency` tool FIRST to convert the trip cost to the budget currency. You cannot skip this step.
4. After you have both amounts in the same currency (either initially or after conversion), you MUST call the `check_budget_feasibility` tool with both currency codes.
5. Do NOT call `check_budget_feasibility` if the currencies are different.

Tools:
- `convert_currency(amount, from_currency, to_currency)`: Use this if currencies differ.
- `check_budget_feasibility(total_cost, cost_currency, budget, budget_currency)`: Use this ONLY when currencies match.

Reply using the tools provided."""

TOOLS = [convert_currency, check_budget_feasibility]


def _build_llm() -> ChatOllama:
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_HOST,
        temperature=0,
        num_ctx=2048,
    )


def build_agent(llm: ChatOllama | None = None):
    """
    Build and return the LangGraph agent for Travel Budget Planner.
    Uses StateGraph with ToolNode and autonomous loop.
    """
    if llm is None:
        llm = _build_llm()

    tool_node = ToolNode(TOOLS)
    llm_with_tools = llm.bind_tools(TOOLS)

    def llm_node(state: AgentState) -> AgentState:
        # Prepend system prompt if not present
        has_system = any(isinstance(m, SystemMessage) for m in state["messages"])
        msgs = state["messages"] if has_system else [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = llm_with_tools.invoke(msgs)
        return {
            "messages": [response],
            "iterations": state.get("iterations", 0) + 1,
        }

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", [])
        if tool_calls and state.get("iterations", 0) >= MAX_ITERATIONS:
            raise RuntimeError(
                f"Agent exceeded the maximum of {MAX_ITERATIONS} model iterations."
            )
        return "tools" if tool_calls else "end"

    graph = StateGraph(AgentState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")

    return graph.compile()


# Singleton agent — built once at import time
agent = build_agent()


def _invoke_agent(messages: list) -> dict:
    """Invoke the compiled LangGraph agent with retry on transient errors."""
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    import httpx

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _inner(messages: list) -> dict:
        return agent.invoke(messages, config={"recursion_limit": MAX_ITERATIONS * 3})

    return _inner(messages)


def run_agent(query: str) -> list:
    """Run the agent on a user query and return the full message list with retry handling."""
    from langchain_core.messages import AIMessage, HumanMessage

    # Prepare the input payload for the agent
    payload = {"messages": [HumanMessage(content=query)]}
    result = _invoke_agent(payload)
    messages = result.get("messages")
    if not messages:
        raise RuntimeError("Agent completed without returning any messages.")
    if not isinstance(messages[-1], AIMessage) or getattr(messages[-1], "tool_calls", []):
        raise RuntimeError("Agent stopped without producing a final assistant response.")
    return messages
