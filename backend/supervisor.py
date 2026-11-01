"""Persistent LangGraph supervisor for planning conversations."""

from __future__ import annotations

import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .config import DATABASE_PATH
from .models import Bid, CostEvidence, TripPlanResponse, TripPreferences
from .planning import (
    apply_follow_up,
    create_budget_bid,
    create_itinerary_bid,
    rank_bids,
    run_reconstructed_single_agent,
)
from .rag import DestinationCostGuide


class PlanningState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    trip_id: str
    preferences: dict
    evidence: dict
    baseline_bid: dict
    budget_bid: dict
    itinerary_bid: dict
    result: dict
    prior_decisions: list[dict]


def build_supervisor():
    def retrieve_node(state: PlanningState) -> PlanningState:
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[-1], HumanMessage):
            raise ValueError("A planning request must include a user message.")
        preferences = TripPreferences.model_validate(state["preferences"])
        preferences = apply_follow_up(preferences, messages[-1].content)
        evidence = DestinationCostGuide().retrieve(preferences.destination)
        if evidence is None:
            raise LookupError(
                f"No illustrative cost-guide data exists for {preferences.destination}."
            )
        return {
            "preferences": preferences.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
        }

    def currency_node(state: PlanningState) -> PlanningState:
        preferences = TripPreferences.model_validate(state["preferences"])
        evidence = CostEvidence.model_validate(state["evidence"])
        baseline = run_reconstructed_single_agent(preferences, evidence)
        return {"baseline_bid": baseline.model_dump(mode="json")}

    def budget_node(state: PlanningState) -> PlanningState:
        preferences = TripPreferences.model_validate(state["preferences"])
        evidence = CostEvidence.model_validate(state["evidence"])
        baseline = Bid.model_validate(state["baseline_bid"])
        bid = create_budget_bid(preferences, evidence, baseline)
        return {"budget_bid": bid.model_dump(mode="json")}

    def itinerary_node(state: PlanningState) -> PlanningState:
        preferences = TripPreferences.model_validate(state["preferences"])
        evidence = CostEvidence.model_validate(state["evidence"])
        baseline = Bid.model_validate(state["baseline_bid"])
        bid = create_itinerary_bid(preferences, evidence, baseline)
        return {"itinerary_bid": bid.model_dump(mode="json")}

    def rank_node(state: PlanningState) -> PlanningState:
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[-1], HumanMessage):
            raise ValueError("A planning request must include a user message.")
        preferences = TripPreferences.model_validate(state["preferences"])
        evidence = CostEvidence.model_validate(state["evidence"])
        result = rank_bids(
            preferences,
            evidence,
            state["trip_id"],
            Bid.model_validate(state["baseline_bid"]),
            Bid.model_validate(state["budget_bid"]),
            Bid.model_validate(state["itinerary_bid"]),
        )
        prior_decisions = list(state.get("prior_decisions", []))
        previous_result = state.get("result")
        if previous_result:
            prior_decisions.append(
                {
                    "selected_bid": previous_result.get("selected_bid"),
                    "rationale": previous_result.get("rationale"),
                    "budget": previous_result.get("preferences", {}).get("budget"),
                    "currency": previous_result.get("preferences", {}).get("currency"),
                }
            )
        result["prior_decisions"] = prior_decisions
        assistant_message = AIMessage(content=result["answer"])
        result["conversation"] = [
            {"role": "user" if isinstance(message, HumanMessage) else "assistant",
             "content": str(message.content)}
            for message in messages
            if isinstance(message, HumanMessage) or getattr(message, "type", "") == "ai"
        ] + [{"role": "assistant", "content": result["answer"]}]
        return {
            "messages": [assistant_message],
            "preferences": preferences.model_dump(mode="json"),
            "prior_decisions": prior_decisions,
            "result": json.loads(
                TripPlanResponse.model_validate(result).model_dump_json()
            ),
        }

    graph = StateGraph(PlanningState)
    graph.add_node("retrieve_context", retrieve_node)
    graph.add_node("currency_agent", currency_node)
    graph.add_node("budget_agent", budget_node)
    graph.add_node("itinerary_agent", itinerary_node)
    graph.add_node("supervisor", rank_node)
    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "currency_agent")
    graph.add_edge("currency_agent", "budget_agent")
    graph.add_edge("currency_agent", "itinerary_agent")
    graph.add_edge(["budget_agent", "itinerary_agent"], "supervisor")
    graph.add_edge("supervisor", END)
    return graph


def run_planning_thread(
    trip_id: str,
    query: str,
    preferences: TripPreferences,
    checkpointer: BaseCheckpointSaver | None = None,
) -> TripPlanResponse:
    def invoke(saver: BaseCheckpointSaver) -> TripPlanResponse:
        graph = build_supervisor().compile(checkpointer=saver)
        state = graph.invoke(
            {
                "trip_id": trip_id,
                "preferences": preferences.model_dump(mode="json"),
                "messages": [HumanMessage(content=query)],
            },
            config={"configurable": {"thread_id": trip_id}},
        )
        return TripPlanResponse.model_validate(state["result"])

    if checkpointer is not None:
        return invoke(checkpointer)
    with SqliteSaver.from_conn_string(str(DATABASE_PATH)) as saver:
        return invoke(saver)


def get_saved_plan(trip_id: str) -> TripPlanResponse | None:
    with SqliteSaver.from_conn_string(str(DATABASE_PATH)) as checkpointer:
        graph = build_supervisor().compile(checkpointer=checkpointer)
        state = graph.get_state(
            {"configurable": {"thread_id": trip_id}}
        )
    result = state.values.get("result")
    return TripPlanResponse.model_validate(result) if result else None
