"""Regenerate the deterministic Unit 3/4 example output and comparison JSON."""

from __future__ import annotations

import json
import gc
import sys
import time
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.models import TripPreferences
from backend.persistence import TripStore
from backend.planning import generate_plan, run_reconstructed_single_agent
from backend.rag import DestinationCostGuide
from backend import supervisor
from langgraph.checkpoint.sqlite import SqliteSaver

SCENARIO = TripPreferences(
    destination="Goa",
    start_date=date(2026, 11, 1),
    end_date=date(2026, 11, 6),
    travelers=2,
    budget=30000,
    currency="INR",
    budget_style="moderate",
    preferred_accommodation_type="hotel",
    food_preferences=["vegetarian"],
    interests=["beaches", "heritage"],
)


def main() -> None:
    guide = DestinationCostGuide()
    evidence = guide.retrieve(SCENARIO.destination)
    if evidence is None:
        raise RuntimeError("The evidence destination is missing from the cost guide.")

    baseline_start = time.perf_counter()
    baseline_bid = run_reconstructed_single_agent(SCENARIO, evidence)
    baseline_ms = round((time.perf_counter() - baseline_start) * 1000, 3)

    multi_start = time.perf_counter()
    plan = generate_plan(SCENARIO, evidence, "unit3-unit4-goa-scenario")
    multi_ms = round((time.perf_counter() - multi_start) * 1000, 3)

    with tempfile.TemporaryDirectory(prefix="travel-planner-evidence-") as directory:
        db_path = Path(directory) / "thread-memory.sqlite3"
        store = TripStore(db_path)
        store.save_preferences("memory-demo", SCENARIO)
        with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
            first = supervisor.run_planning_thread(
                "memory-demo", "Plan this Goa trip.", SCENARIO, checkpointer
            )
            store.append_conversation("memory-demo", "Plan this Goa trip.", first.answer)
            reduced = supervisor.run_planning_thread(
                "memory-demo", "Reduce my budget to ₹15,000.", first.preferences, checkpointer
            )
            store.save_preferences("memory-demo", reduced.preferences)
            store.append_conversation(
                "memory-demo", "Reduce my budget to ₹15,000.", reduced.answer
            )
            more_travelers = supervisor.run_planning_thread(
                "memory-demo", "What if two more people join?", reduced.preferences, checkpointer
            )
            store.save_preferences("memory-demo", more_travelers.preferences)
            store.append_conversation(
                "memory-demo",
                "What if two more people join?",
                more_travelers.answer,
            )
            thread_turns = store.get_conversation("memory-demo")
        del checkpointer
        gc.collect()

    output = {
        "scenario": SCENARIO.model_dump(mode="json"),
        "assumptions": evidence.assumptions,
        "retrieved_evidence": evidence.model_dump(mode="json"),
        "reconstructed_single_agent_baseline": {
            "label": "Reconstructed single-agent baseline; not an authentic prior TA1 rerun",
            "bid": baseline_bid.model_dump(mode="json"),
            "proposal_count": 1,
            "execution_time_ms": baseline_ms,
            "budget_gap": max(0, round(baseline_bid.proposed_total_cost - SCENARIO.budget, 2)),
        },
        "supervised_multi_agent": {
            "bids": [bid.model_dump(mode="json") for bid in plan["bids"]],
            "selected_bid": plan["selected_bid"].model_dump(mode="json") if plan["selected_bid"] else None,
            "itinerary": [day.model_dump(mode="json") for day in plan["itinerary"]],
            "answer": plan["answer"],
            "rationale": plan["rationale"],
            "execution_trace": plan["trace"],
            "proposal_count": len(plan["bids"]),
            "execution_time_ms": multi_ms,
        },
        "comparison": plan["comparison"],
        "thread_memory_demonstration": {
            "thread_id": "memory-demo",
            "turns": thread_turns,
            "after_budget_follow_up": {
                "budget": reduced.preferences.budget,
                "currency": reduced.preferences.currency,
                "feasibility": reduced.feasibility,
            },
            "after_traveler_follow_up": {
                "travelers": more_travelers.preferences.travelers,
                "budget": more_travelers.preferences.budget,
            },
        },
        "reproducible_command": (
            ".\\venv\\Scripts\\python.exe scripts\\generate_unit3_unit4_evidence.py"
        ),
    }
    destination = ROOT / "docs" / "UNIT3_UNIT4_EVIDENCE.json"
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reproducible run output to {destination}")
    print(f"Baseline total: {baseline_bid.proposed_total_cost:.2f} INR")
    print(f"Selected bid: {plan['selected_bid'].bid_id if plan['selected_bid'] else 'none'}")
    print(f"Selected total: {plan['selected_bid'].proposed_total_cost if plan['selected_bid'] else 'none'} INR")


if __name__ == "__main__":
    main()
