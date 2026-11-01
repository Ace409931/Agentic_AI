"""Grounded cost estimation, specialized bid generators, and supervisor ranking."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .models import Bid, CostEvidence, ItineraryDay, TripPreferences
from .rag import DestinationCostGuide
from .tools import CURRENCY_ALIASES, EXCHANGE_RATES

_STYLES = ("budget", "moderate", "luxury")


def normalize_currency(code: str) -> str:
    value = code.strip()
    return CURRENCY_ALIASES.get(value.upper(), CURRENCY_ALIASES.get(value, value.upper()))


class CurrencyAgent:
    """Normalizes deterministic guide estimates using configured demo rates only."""

    @staticmethod
    def convert(amount: float, source: str, target: str) -> tuple[float, float]:
        source_code = normalize_currency(source)
        target_code = normalize_currency(target)
        if source_code == target_code:
            return round(amount, 2), 1.0
        if source_code in EXCHANGE_RATES and target_code in EXCHANGE_RATES[source_code]:
            rate = EXCHANGE_RATES[source_code][target_code]
        elif target_code in EXCHANGE_RATES and source_code in EXCHANGE_RATES[target_code]:
            rate = 1 / EXCHANGE_RATES[target_code][source_code]
        else:
            raise ValueError(
                f"No demonstration exchange rate is available from {source_code} to {target_code}."
            )
        return round(amount * rate, 2), rate


class BudgetAgent:
    """Creates a cost-down bid using the cheapest retrieved daily tiers."""

    @staticmethod
    def propose(
        preferences: TripPreferences,
        evidence: CostEvidence,
        baseline: dict[str, float],
        comparison_currency: str,
        baseline_total: float,
    ) -> tuple[dict[str, float], list[str], list[str]]:
        itemized: dict[str, float] = {}
        changes: list[str] = []
        source_estimates = evidence.estimates
        for category in ("hotel", "food", "transport", "activities"):
            levels = source_estimates.get(category, {})
            if preferences.preferred_accommodation_type != "hotel" and category == "hotel":
                raise ValueError(
                    f"The guide has no {preferences.preferred_accommodation_type} estimates for "
                    f"{preferences.destination}; no grounded bid can be generated."
                )
            if "budget" not in levels:
                raise ValueError(f"The guide has no budget-tier {category} estimate.")
            if category == "hotel":
                quantity = max((preferences.end_date - preferences.start_date).days, 1)
            else:
                quantity = (preferences.end_date - preferences.start_date).days + 1
            raw_amount = levels["budget"] * quantity * preferences.travelers
            converted, _ = CurrencyAgent.convert(
                raw_amount, evidence.currency, comparison_currency
            )
            itemized[category] = converted
            current_amount = baseline[category]
            if converted < current_amount:
                changes.append(f"Use the guide's budget-tier {category} estimate.")
        if (
            "keep_accommodation" in preferences.hard_constraints
            and any("hotel" in change for change in changes)
        ):
            changes = [change for change in changes if "hotel" not in change]
            converted, _ = CurrencyAgent.convert(
                evidence.estimates["hotel"][preferences.budget_style]
                * max((preferences.end_date - preferences.start_date).days, 1)
                * preferences.travelers,
                evidence.currency,
                comparison_currency,
            )
            itemized["hotel"] = converted
        if (
            "no_activity_reduction" in preferences.hard_constraints
            and any("activities" in change for change in changes)
        ):
            changes = [change for change in changes if "activities" not in change]
            itemized["activities"] = baseline["activities"]
        return itemized, changes, [
            "Uses guide estimates, not live prices.",
            "Budget-tier alternatives may reduce comfort or activity choices.",
        ]


class ItineraryAgent:
    """Creates a bid by scheduling one guide-costed low-cost/rest activity day."""

    @staticmethod
    def propose(
        preferences: TripPreferences,
        evidence: CostEvidence,
        baseline: dict[str, float],
        comparison_currency: str,
    ) -> tuple[dict[str, float], list[str], list[str]]:
        itemized = dict(baseline)
        days = (preferences.end_date - preferences.start_date).days + 1
        if days > 1:
            current_daily_activity = evidence.estimates["activities"][preferences.budget_style]
            avoided, _ = CurrencyAgent.convert(
                current_daily_activity * preferences.travelers,
                evidence.currency,
                comparison_currency,
            )
            itemized["activities"] = max(0.0, round(itemized["activities"] - avoided, 2))
            changes = ["Schedule one low-cost/rest day instead of a paid-activity day."]
        else:
            changes = ["Retain the one-day itinerary; no activity day can be removed."]
        if "no_activity_reduction" in preferences.hard_constraints:
            itemized = dict(baseline)
            changes = ["No activity reduction applied because it is a hard constraint."]
        return itemized, changes, [
            "The proposed rest day avoids one day of the guide's estimated paid-activity spending.",
            "Transport, accommodation, and food assumptions stay unchanged.",
        ]

    @staticmethod
    def build_schedule(
        preferences: TripPreferences,
        selected_bid: Bid,
    ) -> list[ItineraryDay]:
        days = (preferences.end_date - preferences.start_date).days + 1
        daily_activity = (
            selected_bid.itemized_costs["activities"] / preferences.travelers / days
        )
        interests = ", ".join(preferences.interests) or "local sightseeing"
        food = ", ".join(preferences.food_preferences) or "local dining"
        itinerary = []
        for offset in range(days):
            if offset == 0:
                plan = (
                    f"Arrival, settle in, and explore nearby low-cost {interests}; "
                    f"consider {food} options."
                )
            elif offset == days - 1:
                plan = (
                    f"Flexible final day for {interests}, then departure; "
                    f"leave time for local transport."
                )
            elif (
                selected_bid.agent_name == "itinerary_agent"
                and 0 < offset < days - 1
                and offset == days // 2
            ):
                plan = "Low-cost/rest day with free local sightseeing instead of a paid activity."
            elif (
                selected_bid.agent_name == "itinerary_agent"
                and days == 2
                and offset == days - 1
            ):
                plan = "Flexible departure day with no paid activity scheduled; use nearby low-cost sightseeing."
            elif selected_bid.agent_name == "budget_agent":
                plan = f"Choose budget-tier activities related to {interests}."
            else:
                plan = f"Explore {interests} using the selected itinerary style."
            itinerary.append(
                ItineraryDay(
                    day=offset + 1,
                    date=preferences.start_date + timedelta(days=offset),
                    plan=plan,
                    estimated_activity_cost=round(daily_activity, 2),
                    currency=selected_bid.comparison_currency,
                )
            )
        return itinerary


def _parse_style_change(message: str, current_style: str) -> str:
    text = message.casefold()
    if re.search(
        r"\b(?:budget\s+(?:style|trip|hotel|tier)|budget-tier|travel on a budget)\b",
        text,
    ):
        return "budget"
    for style in ("moderate", "luxury"):
        if re.search(rf"\b{style}\b", text):
            return style
    if "cheaper hotel" in text or "cheaper hotels" in text or "more budget" in text:
        return "budget"
    if "more luxurious" in text or "upgrade" in text:
        return "luxury"
    return current_style


def apply_follow_up(preferences: TripPreferences, message: str) -> TripPreferences:
    updated = preferences.model_dump()
    text = message.casefold()
    money = re.search(
        r"(?:budget(?:\s+to|\s+of)?\s*)[₹€£$]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(INR|EUR|USD|GBP)?",
        message,
        re.IGNORECASE,
    )
    if money:
        updated["budget"] = float(money.group(1).replace(",", ""))
        if money.group(2):
            updated["currency"] = normalize_currency(money.group(2))
        elif "₹" in message:
            updated["currency"] = "INR"
        elif "€" in message:
            updated["currency"] = "EUR"
        elif "$" in message:
            updated["currency"] = "USD"
        elif "£" in message:
            updated["currency"] = "GBP"
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
    }
    people = re.search(
        r"\b(\d+|one|two|three|four|five|six)\s+(?:more\s+)?people\s+(?:join|travel)",
        text,
    )
    if people:
        count = int(people.group(1)) if people.group(1).isdigit() else number_words[people.group(1)]
        updated["travelers"] = count if "more" not in text else preferences.travelers + count
    updated["budget_style"] = _parse_style_change(message, preferences.budget_style)
    return TripPreferences.model_validate(updated)


def _trip_estimates(
    preferences: TripPreferences,
    evidence: CostEvidence,
    style: str,
) -> dict[str, float]:
    nights = (preferences.end_date - preferences.start_date).days
    days = nights + 1
    if preferences.preferred_accommodation_type != "hotel":
        raise ValueError(
            f"No {preferences.preferred_accommodation_type} prices are present in the local guide."
        )
    for category in ("hotel", "food", "transport", "activities"):
        if category not in evidence.estimates or style not in evidence.estimates[category]:
            raise ValueError(
                f"The guide lacks a {style}-tier {category} estimate for {evidence.destination}."
            )
    per_category = {
        "hotel": evidence.estimates["hotel"][style] * nights * preferences.travelers,
        "food": evidence.estimates["food"][style] * days * preferences.travelers,
        "transport": evidence.estimates["transport"][style] * days * preferences.travelers,
        "activities": evidence.estimates["activities"][style] * days * preferences.travelers,
    }
    converted = {
        category: CurrencyAgent.convert(amount, evidence.currency, preferences.currency)[0]
        for category, amount in per_category.items()
    }
    return {category: round(amount, 2) for category, amount in converted.items()}


def _trip_original_estimates(
    preferences: TripPreferences,
    evidence: CostEvidence,
    style: str,
) -> dict[str, float]:
    nights = (preferences.end_date - preferences.start_date).days
    days = nights + 1
    return {
        "hotel": round(evidence.estimates["hotel"][style] * nights * preferences.travelers, 2),
        "food": round(evidence.estimates["food"][style] * days * preferences.travelers, 2),
        "transport": round(evidence.estimates["transport"][style] * days * preferences.travelers, 2),
        "activities": round(evidence.estimates["activities"][style] * days * preferences.travelers, 2),
    }


def _create_bid(
    bid_id: str,
    agent_name: str,
    itemized: dict[str, float],
    changes: list[str],
    assumptions: list[str],
    rationale: str,
    baseline: dict[str, float],
    preferences: TripPreferences,
    original_currency: str,
    original_itemized: dict[str, float],
) -> Bid:
    proposed_total = round(sum(itemized.values()), 2)
    baseline_total = round(sum(baseline.values()), 2)
    violations: list[str] = []
    if proposed_total < 0:
        violations.append("Negative total cost.")
    if set(itemized) != {"hotel", "food", "transport", "activities"}:
        violations.append("Bid must contain exactly the four required cost categories.")
    savings = round(baseline_total - proposed_total, 2)
    savings_percentage = round(savings / baseline_total * 100, 2) if baseline_total else 0
    return Bid(
        bid_id=bid_id,
        agent_name=agent_name,
        proposed_changes=changes,
        itemized_costs=itemized,
        original_itemized_costs=original_itemized,
        original_currency=original_currency,
        comparison_currency=preferences.currency,
        exchange_rates={
            category: CurrencyAgent.convert(1, original_currency, preferences.currency)[1]
            for category in itemized
        },
        baseline_cost=baseline_total,
        proposed_total_cost=proposed_total,
        savings_amount=savings,
        savings_percentage=savings_percentage,
        budget_limit=preferences.budget,
        feasible=proposed_total <= preferences.budget and not violations,
        constraint_violations=violations,
        assumptions=assumptions,
        rationale=rationale,
    )


def run_reconstructed_single_agent(
    preferences: TripPreferences,
    evidence: CostEvidence,
) -> Bid:
    """One-pass estimate baseline, reconstructed for comparable cost-guide inputs."""
    itemized = _trip_estimates(preferences, evidence, preferences.budget_style)
    return _create_bid(
        "single-agent-baseline",
        "baseline",
        itemized,
        [],
        ["One-pass estimate from the selected style and the shared local cost guide."],
        "Reconstructed single-agent baseline; not the prior Ollama agent rerun.",
        itemized,
        preferences,
        evidence.currency,
        _trip_original_estimates(preferences, evidence, preferences.budget_style),
    )


def create_budget_bid(
    preferences: TripPreferences,
    evidence: CostEvidence,
    baseline_bid: Bid,
) -> Bid:
    baseline_items = dict(baseline_bid.itemized_costs)
    budget_items, budget_changes, budget_assumptions = BudgetAgent.propose(
        preferences, evidence, baseline_items, preferences.currency,
        baseline_bid.proposed_total_cost,
    )
    budget_styles = {
        category: "budget" for category in ("hotel", "food", "transport", "activities")
    }
    if "keep_accommodation" in preferences.hard_constraints:
        budget_styles["hotel"] = preferences.budget_style
    if "no_activity_reduction" in preferences.hard_constraints:
        budget_styles["activities"] = preferences.budget_style
    budget_original = _trip_original_estimates_by_category(
        preferences, evidence, budget_styles
    )
    return _create_bid(
        "budget-agent",
        "budget_agent",
        budget_items,
        budget_changes,
        budget_assumptions,
        "Uses the lowest retrieved guide tiers while preserving the trip dates and traveler count.",
        baseline_items,
        preferences,
        evidence.currency,
        budget_original,
    )


def create_itinerary_bid(
    preferences: TripPreferences,
    evidence: CostEvidence,
    baseline_bid: Bid,
) -> Bid:
    baseline_items = dict(baseline_bid.itemized_costs)
    baseline_original = dict(baseline_bid.original_itemized_costs)
    itinerary_items, itinerary_changes, itinerary_assumptions = ItineraryAgent.propose(
        preferences, evidence, baseline_items, preferences.currency
    )
    itinerary_original = dict(baseline_original)
    if (
        (preferences.end_date - preferences.start_date).days >= 1
        and "no_activity_reduction" not in preferences.hard_constraints
    ):
        itinerary_original["activities"] = round(
            itinerary_original["activities"]
            - evidence.estimates["activities"][preferences.budget_style] * preferences.travelers,
            2,
        )
    return _create_bid(
        "itinerary-agent",
        "itinerary_agent",
        itinerary_items,
        itinerary_changes,
        itinerary_assumptions,
        "Reduces paid activity spending by scheduling one rest or low-cost day.",
        baseline_items,
        preferences,
        evidence.currency,
        itinerary_original,
    )


def rank_bids(
    preferences: TripPreferences,
    evidence: CostEvidence,
    trip_id: str,
    baseline_bid: Bid,
    budget_bid: Bid,
    itinerary_bid: Bid,
    conversation: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    bids = [baseline_bid, budget_bid, itinerary_bid]
    feasible_bids = [
        bid for bid in bids
        if bid.feasible and not bid.constraint_violations and bid.proposed_total_cost <= preferences.budget
    ]
    selected = min(feasible_bids, key=lambda bid: bid.proposed_total_cost) if feasible_bids else None
    for bid in bids:
        if selected and bid.bid_id == selected.bid_id:
            bid.decision_reason = "Selected as the cheapest valid feasible proposal."
        elif bid.constraint_violations:
            bid.decision_reason = "Rejected because it violates a hard trip constraint."
        elif not bid.feasible:
            bid.decision_reason = (
                f"Rejected because it exceeds the budget by "
                f"{max(0.0, bid.proposed_total_cost - preferences.budget):,.2f} "
                f"{preferences.currency}."
            )
        else:
            bid.decision_reason = (
                f"Feasible, but more expensive than selected bid {selected.bid_id}."
                if selected
                else "No option was selected because no proposal meets the budget."
            )
    if selected:
        rationale = (
            f"Selected {selected.agent_name}: it is the lowest-cost valid proposal that fits "
            f"the {preferences.budget:,.2f} {preferences.currency} budget."
        )
        feasibility = "feasible"
        gap = 0.0
        answer = (
            f"Selected {selected.agent_name} at an estimated "
            f"{selected.proposed_total_cost:,.2f} {preferences.currency}; "
            f"budget is {preferences.budget:,.2f} {preferences.currency}."
        )
    else:
        gap = round(min(bid.proposed_total_cost for bid in bids) - preferences.budget, 2)
        rationale = (
            f"No valid proposal fits the budget. The cheapest option exceeds it by "
            f"{gap:,.2f} {preferences.currency}."
        )
        feasibility = "infeasible"
        answer = rationale
    rejected = [bid for bid in bids if selected is None or bid.bid_id != selected.bid_id]
    itinerary = ItineraryAgent.build_schedule(
        preferences,
        selected or baseline_bid,
    )
    conversation = list(conversation or [])
    trace = [
        {"step": "1", "agent": "RAG", "event": f"Retrieved evidence from {evidence.source_file} section {evidence.section}."},
        {"step": "2", "agent": "Currency Agent", "event": f"Normalized every estimate into {preferences.currency} using configured demo rates."},
        {"step": "3", "agent": "Budget Agent", "event": "Generated deterministic budget-tier proposal."},
        {"step": "4", "agent": "Itinerary Agent", "event": "Generated a rest-day proposal from guide activity estimates."},
        {"step": "5", "agent": "Supervisor", "event": rationale},
    ]
    return {
        "trip_id": trip_id,
        "preferences": preferences,
        "conversation": conversation,
        "evidence": [evidence],
        "bids": bids,
        "selected_bid": selected,
        "rejected_bids": rejected,
        "answer": answer,
        "feasibility": feasibility,
        "budget_gap": gap,
        "rationale": rationale,
        "trace": trace,
        "itinerary": itinerary,
        "comparison": {
            "baseline_label": "Reconstructed single-agent baseline",
            "multi_agent_label": "Three-agent supervised bidding workflow",
            "baseline_total_cost": baseline_bid.proposed_total_cost,
            "baseline_feasible": baseline_bid.feasible,
            "baseline_budget_gap": max(
                0.0, round(baseline_bid.proposed_total_cost - preferences.budget, 2)
            ),
            "baseline_proposal_count": 1,
            "selected_total_cost": selected.proposed_total_cost if selected else None,
            "selected_feasible": selected is not None,
            "multi_agent_budget_gap": gap,
            "multi_agent_proposal_count": len(bids),
            "selected_savings": (
                round(baseline_bid.proposed_total_cost - selected.proposed_total_cost, 2)
                if selected
                else 0.0
            ),
            "constraint_violations": len(selected.constraint_violations) if selected else 0,
        },
    }


def generate_plan(
    preferences: TripPreferences,
    evidence: CostEvidence,
    trip_id: str,
    conversation: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the specialized deterministic agents and rank their bids."""
    baseline_bid = run_reconstructed_single_agent(preferences, evidence)
    budget_bid = create_budget_bid(preferences, evidence, baseline_bid)
    itinerary_bid = create_itinerary_bid(preferences, evidence, baseline_bid)
    return rank_bids(
        preferences,
        evidence,
        trip_id,
        baseline_bid,
        budget_bid,
        itinerary_bid,
        conversation,
    )


def _trip_original_estimates_by_category(
    preferences: TripPreferences,
    evidence: CostEvidence,
    styles: dict[str, str],
) -> dict[str, float]:
    nights = (preferences.end_date - preferences.start_date).days
    days = nights + 1
    quantities = {
        "hotel": nights * preferences.travelers,
        "food": days * preferences.travelers,
        "transport": days * preferences.travelers,
        "activities": days * preferences.travelers,
    }
    return {
        category: round(evidence.estimates[category][styles[category]] * quantity, 2)
        for category, quantity in quantities.items()
    }
