"""Agent workflow tests using a deterministic fake model; no Ollama required."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent import build_agent
from backend.tools import check_budget_feasibility
from backend.tracing import build_trace, extract_structured_data


class FakeToolCallingLLM:
    def __init__(self):
        self.responses = [
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "convert_currency",
                    "args": {
                        "amount": 900,
                        "from_currency": "EUR",
                        "to_currency": "INR",
                    },
                    "id": "convert-1",
                }],
            ),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "check_budget_feasibility",
                    "args": {
                        "total_cost": 85500,
                        "cost_currency": "INR",
                        "budget": 100000,
                        "budget_currency": "INR",
                    },
                    "id": "budget-1",
                }],
            ),
            AIMessage(content="The trip is feasible."),
        ]
        self.call_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


def test_agent_executes_currency_and_budget_tools_in_order():
    llm = FakeToolCallingLLM()
    agent = build_agent(llm=llm)

    result = agent.invoke(
        {"messages": [HumanMessage(content="900 EUR trip, 100000 INR budget")]},
        config={"recursion_limit": 20},
    )
    trace = build_trace(result["messages"])

    assert [event.step for event in trace] == list(range(1, len(trace) + 1))
    assert [event.tool for event in trace if event.type == "tool_call"] == [
        "convert_currency",
        "check_budget_feasibility",
    ]
    structured = extract_structured_data(trace)
    assert structured == {
        "feasible": True,
        "total_cost": 85500.0,
        "budget": 100000.0,
        "currency": "INR",
        "remaining": 14500.0,
        "overage": None,
    }
    assert llm.call_count == 3


def test_agent_propagates_model_errors():
    class FailingLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            raise RuntimeError("model unavailable")

    agent = build_agent(llm=FailingLLM())
    with pytest.raises(RuntimeError, match="model unavailable"):
        agent.invoke(
            {"messages": [HumanMessage(content="Can I afford the trip?")]},
            config={"recursion_limit": 20},
        )


def test_structured_feasibility_preserves_python_remaining_and_overage_values():
    feasible_text = check_budget_feasibility.invoke(
        {
            "total_cost": 85500,
            "cost_currency": "INR",
            "budget": 100000,
            "budget_currency": "INR",
        }
    )
    infeasible_text = check_budget_feasibility.invoke(
        {
            "total_cost": 85500,
            "cost_currency": "INR",
            "budget": 50000,
            "budget_currency": "INR",
        }
    )

    feasible = extract_structured_data(
        build_trace(
            [
                ToolMessage(
                    content=feasible_text,
                    tool_call_id="feasible-1",
                    name="check_budget_feasibility",
                )
            ]
        )
    )
    infeasible = extract_structured_data(
        build_trace(
            [
                ToolMessage(
                    content=infeasible_text,
                    tool_call_id="infeasible-1",
                    name="check_budget_feasibility",
                )
            ]
        )
    )

    assert feasible["remaining"] == 14500
    assert feasible["overage"] is None
    assert infeasible["remaining"] is None
    assert infeasible["overage"] == 35500
