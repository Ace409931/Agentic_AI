"""Persistent trip planner, retrieval, cost, and supervisor regression tests."""

from datetime import date

import pytest

from backend.models import TripPreferences
from backend.persistence import TripStore
from backend.planning import (
    BudgetAgent,
    CurrencyAgent,
    ItineraryAgent,
    apply_follow_up,
    generate_plan,
)
from backend.rag import DestinationCostGuide


@pytest.fixture
def preferences():
    return TripPreferences(
        destination="Goa",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
        travelers=2,
        budget=30000,
        currency="INR",
        budget_style="moderate",
        preferred_accommodation_type="hotel",
        food_preferences=["vegetarian"],
        interests=["beaches", "history"],
    )


def test_preferences_persist_and_update_between_store_instances(tmp_path, preferences):
    database = tmp_path / "planner.sqlite3"
    TripStore(database).save_preferences("trip-one", preferences)

    reopened = TripStore(database).get_preferences("trip-one")

    assert reopened == preferences
    assert TripStore(database).get_preferences("missing") is None


def test_preferences_reject_invalid_date_currency_and_traveler_count(preferences):
    data = preferences.model_dump()
    data["end_date"] = date(2026, 10, 31)
    with pytest.raises(ValueError, match="end_date"):
        TripPreferences.model_validate(data)

    data = preferences.model_dump()
    data["currency"] = "JPY"
    with pytest.raises(ValueError, match="currency"):
        TripPreferences.model_validate(data)

    data = preferences.model_dump()
    data["travelers"] = 0
    with pytest.raises(ValueError):
        TripPreferences.model_validate(data)


def test_rag_retrieves_destination_and_categories(tmp_path):
    guide = DestinationCostGuide()

    goa = guide.retrieve("goa", categories=["hotel", "food"])

    assert goa is not None
    assert goa.destination == "Goa"
    assert set(goa.estimates) == {"hotel", "food"}
    assert goa.estimates["hotel"]["moderate"] == 2500
    assert goa.source_file == "destination_cost_guide.txt"
    assert guide.retrieve("Atlantis") is None


def test_rag_returns_empty_for_missing_category():
    evidence = DestinationCostGuide().retrieve("Goa", categories=["flights"])

    assert evidence is not None
    assert evidence.estimates == {}


def test_planner_does_not_invent_missing_destination_category(preferences):
    evidence = DestinationCostGuide().retrieve("Goa", categories=["hotel", "food"])

    with pytest.raises(ValueError, match="lacks a moderate-tier transport estimate"):
        generate_plan(preferences, evidence, "missing-category")


def test_currency_agent_normalizes_direct_and_inverse_rates():
    assert CurrencyAgent.convert(100, "EUR", "INR") == (9500, 95.0)
    converted, rate = CurrencyAgent.convert(9500, "INR", "EUR")
    assert converted == pytest.approx(99.75)
    assert rate == 0.0105
    with pytest.raises(ValueError, match="No demonstration exchange rate"):
        CurrencyAgent.convert(100, "JPY", "INR")


def test_cross_currency_bids_keep_source_amounts_and_conversion_assumptions(preferences):
    paris_preferences = preferences.model_copy(
        update={"destination": "Paris", "currency": "INR", "budget": 1_000_000}
    )
    evidence = DestinationCostGuide().retrieve("Paris")
    plan = generate_plan(paris_preferences, evidence, "paris-cross-currency")
    baseline = plan["bids"][0]

    assert baseline.original_currency == "EUR"
    assert baseline.comparison_currency == "INR"
    assert baseline.original_itemized_costs["hotel"] == 1500
    assert baseline.itemized_costs["hotel"] == 142500
    assert set(baseline.exchange_rates.values()) == {95.0}


def test_budget_and_itinerary_agents_use_retrieved_costs(preferences):
    evidence = DestinationCostGuide().retrieve("Goa")
    assert evidence is not None
    baseline = {"hotel": 25000, "food": 10800, "transport": 6000, "activities": 14400}

    budget_costs, changes, _ = BudgetAgent.propose(
        preferences, evidence, baseline, "INR", sum(baseline.values())
    )
    itinerary_costs, itinerary_changes, _ = ItineraryAgent.propose(
        preferences, evidence, baseline, "INR"
    )

    assert budget_costs == {"hotel": 12000, "food": 5400, "transport": 6000, "activities": 4800}
    assert len(changes) == 3
    assert itinerary_costs["activities"] == 12000
    assert itinerary_changes


def test_supervisor_selects_lowest_valid_feasible_bid(preferences):
    evidence = DestinationCostGuide().retrieve("Goa")
    result = generate_plan(preferences, evidence, "goa-trip")

    assert result["bids"][0].proposed_total_cost == 56200
    assert result["selected_bid"].agent_name == "budget_agent"
    assert result["selected_bid"].proposed_total_cost == 28200
    assert result["selected_bid"].feasible is True
    assert result["rejected_bids"]
    assert "lowest-cost valid proposal" in result["rationale"]
    assert len(result["itinerary"]) == 6
    assert result["itinerary"][0].date == preferences.start_date
    assert "booking" not in result["itinerary"][0].plan.casefold()


def test_supervisor_reports_no_feasible_bid_and_budget_gap(preferences):
    preferences = preferences.model_copy(update={"budget": 1000})
    evidence = DestinationCostGuide().retrieve("Goa")

    result = generate_plan(preferences, evidence, "low-budget-trip")

    assert result["selected_bid"] is None
    assert result["feasibility"] == "infeasible"
    assert result["budget_gap"] == 27200
    assert "No valid proposal fits" in result["answer"]


def test_hard_constraints_are_preserved_in_budget_proposal(preferences):
    constrained = preferences.model_copy(
        update={
            "budget": 100000,
            "hard_constraints": ["keep_accommodation", "no_activity_reduction"],
        }
    )
    evidence = DestinationCostGuide().retrieve("Goa")
    result = generate_plan(constrained, evidence, "constrained-trip")
    budget_bid = next(bid for bid in result["bids"] if bid.agent_name == "budget_agent")

    assert budget_bid.itemized_costs["hotel"] == 25000
    assert budget_bid.itemized_costs["activities"] == 14400
    assert not budget_bid.constraint_violations
    assert result["selected_bid"].proposed_total_cost == 50800


def test_follow_up_updates_budget_currency_and_travelers(preferences):
    updated = apply_follow_up(preferences, "Reduce my budget to ₹15,000")
    assert updated.budget == 15000
    assert updated.currency == "INR"
    assert updated.budget_style == "moderate"

    updated = apply_follow_up(preferences, "What if two more people join?")
    assert updated.travelers == 4

    updated = apply_follow_up(preferences, "Keep same destination but choose cheaper hotels")
    assert updated.destination == "Goa"
    assert updated.budget_style == "budget"
