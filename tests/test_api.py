"""FastAPI tests with Ollama and model execution mocked out."""

import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend import main
from backend import supervisor
from backend.persistence import TripStore


client = TestClient(main.app)


def test_health_reports_unavailable_ollama(monkeypatch):
    monkeypatch.setattr(main, "_ollama_status", AsyncMock(return_value=(False, False)))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ollama_reachable"] is False
    assert response.json()["model_available"] is False
    assert "ollama serve" in response.json()["message"]


def test_stream_returns_service_unavailable_when_ollama_is_down(monkeypatch):
    monkeypatch.setattr(main, "_ollama_status", AsyncMock(return_value=(False, False)))

    response = client.post("/api/analyze/stream", json={"query": "Can I afford this trip?"})

    assert response.status_code == 503
    assert "Ollama is unavailable" in response.json()["detail"]


def test_analyze_rejects_blank_query():
    response = client.post("/api/analyze", json={"query": "  "})

    assert response.status_code == 422


def test_analyze_returns_response_matching_frontend_contract(monkeypatch):
    monkeypatch.setattr(main, "_ollama_status", AsyncMock(return_value=(True, True)))

    def fake_run_agent(query):
        assert query == "Check my travel budget"
        return [
            HumanMessage(content=query),
            AIMessage(content="The trip is feasible."),
        ]

    monkeypatch.setattr("backend.agent.run_agent", fake_run_agent)

    response = client.post(
        "/api/analyze",
        json={"query": "  Check my travel budget  "},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "The trip is feasible."
    assert response.json()["trace"]


def test_analyze_returns_safe_error_when_agent_fails(monkeypatch):
    monkeypatch.setattr(main, "_ollama_status", AsyncMock(return_value=(True, True)))

    def fail_agent(query):
        raise RuntimeError("private internal failure")

    monkeypatch.setattr("backend.agent.run_agent", fail_agent)

    response = client.post("/api/analyze", json={"query": "Can I afford this trip?"})

    assert response.status_code == 500
    assert "agent failed" in response.json()["detail"].lower()
    assert "private internal failure" not in response.text


def test_stream_emits_complete_event_for_final_agent_state(monkeypatch):
    monkeypatch.setattr(main, "_ollama_status", AsyncMock(return_value=(True, True)))

    class FakeAgent:
        async def astream_events(self, inputs, version):
            assert version == "v2"
            assert inputs["messages"][0].content == "Check my travel budget"
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {
                    "output": {
                        "messages": [
                            HumanMessage(content="Check my travel budget"),
                            AIMessage(content="The trip is feasible."),
                        ]
                    }
                },
            }

    monkeypatch.setattr("backend.agent.agent", FakeAgent())

    response = client.post(
        "/api/analyze/stream",
        json={"query": "Check my travel budget"},
    )

    assert response.status_code == 200
    assert '"type": "complete"' in response.text
    assert '"answer": "The trip is feasible."' in response.text
    assert "[DONE]" in response.text


def test_stream_values_and_trace_belong_to_the_submitted_query(monkeypatch):
    query = "I have ₹100,000 and my estimated trip cost is €900. Can I afford it?"
    monkeypatch.setattr(main, "_ollama_status", AsyncMock(return_value=(True, True)))

    class FakeAgent:
        async def astream_events(self, inputs, version):
            assert inputs["messages"][0].content == query
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {
                    "output": {
                        "messages": [
                            HumanMessage(content=query),
                            AIMessage(
                                content="",
                                tool_calls=[
                                    {
                                        "name": "convert_currency",
                                        "args": {
                                            "amount": 900,
                                            "from_currency": "EUR",
                                            "to_currency": "INR",
                                        },
                                        "id": "convert-1",
                                    }
                                ],
                            ),
                            ToolMessage(
                                content="Converted 900 EUR to 85500 INR using the demonstration rate.",
                                tool_call_id="convert-1",
                                name="convert_currency",
                            ),
                            AIMessage(
                                content="Trip is feasible.",
                                tool_calls=[
                                    {
                                        "name": "check_budget_feasibility",
                                        "args": {
                                            "total_cost": 85500,
                                            "cost_currency": "INR",
                                            "budget": 100000,
                                            "budget_currency": "INR",
                                        },
                                        "id": "budget-1",
                                    }
                                ],
                            ),
                            ToolMessage(
                                content=(
                                    "Trip is feasible. Total cost is 85500 INR and the "
                                    "budget is 100000 INR. Remaining budget: 14500 INR."
                                ),
                                tool_call_id="budget-1",
                                name="check_budget_feasibility",
                            ),
                            AIMessage(content="Yes. INR 14,500 remains."),
                        ]
                    }
                },
            }

    monkeypatch.setattr("backend.agent.agent", FakeAgent())

    response = client.post("/api/analyze/stream", json={"query": query})

    assert response.status_code == 200
    event = next(
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: {") and '"type": "complete"' in line
    )
    assert event["feasible"] is True
    assert event["total_cost"] == 85500
    assert event["budget"] == 100000
    assert event["remaining"] == 14500
    assert event["overage"] is None
    assert event["currency"] == "INR"
    assert event["trace"][0]["description"] == query


def test_trip_preferences_and_thread_plan_api(tmp_path, monkeypatch):
    database = tmp_path / "api-planner.sqlite3"
    store = TripStore(database)
    monkeypatch.setattr(main, "TripStore", lambda: store)
    monkeypatch.setattr(supervisor, "DATABASE_PATH", database)
    trip_id = "api-thread-goa"
    payload = {
        "destination": "Goa",
        "start_date": "2026-11-01",
        "end_date": "2026-11-06",
        "travelers": 2,
        "budget": 30000,
        "currency": "INR",
        "budget_style": "moderate",
        "preferred_accommodation_type": "hotel",
        "food_preferences": ["vegetarian"],
        "interests": ["beaches"],
        "hard_constraints": [],
    }

    saved = client.put(f"/api/trips/{trip_id}/preferences", json=payload)
    planned = client.post(
        f"/api/trips/{trip_id}/plan",
        json={"query": "Plan my Goa trip and compare lower-cost options."},
    )
    followed_up = client.post(
        f"/api/trips/{trip_id}/plan",
        json={"query": "Reduce my budget to ₹15,000."},
    )
    restored = client.get(f"/api/trips/{trip_id}/plan")

    assert saved.status_code == 200
    assert planned.status_code == 200
    assert planned.json()["selected_bid"]["bid_id"] == "budget-agent"
    assert followed_up.status_code == 200
    assert followed_up.json()["preferences"]["budget"] == 15000
    assert followed_up.json()["conversation"][-2]["role"] == "user"
    assert restored.status_code == 200
    assert restored.json()["preferences"]["budget"] == 15000
    assert len(restored.json()["conversation"]) == 4


def test_trip_planning_rejects_unknown_destination(tmp_path, monkeypatch):
    database = tmp_path / "api-unknown.sqlite3"
    store = TripStore(database)
    monkeypatch.setattr(main, "TripStore", lambda: store)
    monkeypatch.setattr(supervisor, "DATABASE_PATH", database)
    saved = client.put(
        "/api/trips/unknown-destination/preferences",
        json={
            "destination": "Atlantis",
            "start_date": "2026-11-01",
            "end_date": "2026-11-06",
            "travelers": 2,
            "budget": 30000,
            "currency": "INR",
            "budget_style": "moderate",
        },
    )
    assert saved.status_code == 200

    response = client.post(
        "/api/trips/unknown-destination/plan",
        json={"query": "Plan my trip."},
    )

    assert response.status_code == 404
    assert "No illustrative cost-guide data" in response.json()["detail"]
