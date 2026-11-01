"""
Pydantic request/response schemas for the Travel Budget Planner API.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Natural-language travel-budget question from the user.",
        examples=["I have a budget of ₹100000 and my estimated trip cost is €900. Can I afford it?"],
    )

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class TripPreferences(BaseModel):
    destination: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    travelers: int = Field(ge=1, le=20)
    budget: float = Field(gt=0, le=1_000_000_000)
    currency: str = Field(min_length=3, max_length=3)
    budget_style: Literal["budget", "moderate", "luxury"] = "moderate"
    preferred_accommodation_type: Literal["hotel", "hostel", "rental"] = "hotel"
    food_preferences: list[str] = Field(default_factory=list, max_length=20)
    interests: list[str] = Field(default_factory=list, max_length=30)
    hard_constraints: list[
        Literal["keep_accommodation", "no_activity_reduction"]
    ] = Field(default_factory=list, max_length=20)

    @field_validator("destination")
    @classmethod
    def normalize_destination(cls, value: str) -> str:
        return value.strip()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        aliases = {"₹": "INR", "€": "EUR", "$": "USD", "£": "GBP"}
        normalized = aliases.get(value.strip(), normalized)
        if normalized not in {"INR", "EUR", "USD", "GBP"}:
            raise ValueError("currency must be one of INR, EUR, USD, or GBP")
        return normalized

    @field_validator("food_preferences", "interests", "hard_constraints")
    @classmethod
    def normalize_list_values(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]

    @field_validator("budget")
    @classmethod
    def validate_finite_budget(cls, value: float) -> float:
        import math

        if not math.isfinite(value):
            raise ValueError("budget must be a finite amount")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "TripPreferences":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class TripPlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class CostEvidence(BaseModel):
    destination: str
    currency: str
    section: str
    source_file: str
    estimates: dict[str, dict[str, float]]
    assumptions: list[str]


class Bid(BaseModel):
    bid_id: str
    agent_name: Literal["baseline", "budget_agent", "itinerary_agent"]
    proposed_changes: list[str]
    itemized_costs: dict[str, float]
    original_itemized_costs: dict[str, float] = Field(default_factory=dict)
    original_currency: str
    comparison_currency: str
    exchange_rates: dict[str, float] = Field(default_factory=dict)
    baseline_cost: float = Field(ge=0)
    proposed_total_cost: float = Field(ge=0)
    savings_amount: float
    savings_percentage: float
    budget_limit: float = Field(ge=0)
    feasible: bool
    constraint_violations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    rationale: str
    decision_reason: str = ""

    @field_validator("itemized_costs")
    @classmethod
    def validate_cost_items(cls, values: dict[str, float]) -> dict[str, float]:
        import math

        if not values or any(not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError("itemized costs must be non-empty finite non-negative amounts")
        return values

    @field_validator("exchange_rates")
    @classmethod
    def validate_exchange_rates(cls, values: dict[str, float]) -> dict[str, float]:
        import math

        if any(not math.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("exchange rates must be finite positive amounts")
        return values

    @model_validator(mode="after")
    def validate_totals(self) -> "Bid":
        import math

        if not math.isfinite(self.proposed_total_cost) or not math.isfinite(self.baseline_cost):
            raise ValueError("bid totals must be finite")
        if round(sum(self.itemized_costs.values()), 2) != round(self.proposed_total_cost, 2):
            raise ValueError("itemized costs must sum to proposed_total_cost")
        return self


class ItineraryDay(BaseModel):
    day: int
    date: date
    plan: str
    estimated_activity_cost: float = Field(ge=0)
    currency: str


class TripPlanResponse(BaseModel):
    trip_id: str
    preferences: TripPreferences
    conversation: list[dict[str, str]]
    evidence: list[CostEvidence]
    bids: list[Bid]
    selected_bid: Optional[Bid] = None
    rejected_bids: list[Bid] = Field(default_factory=list)
    answer: str
    feasibility: Literal["feasible", "infeasible", "unavailable"]
    budget_gap: Optional[float] = None
    rationale: str
    trace: list[dict[str, str]]
    comparison: dict[str, Any] = Field(default_factory=dict)
    itinerary: list[ItineraryDay] = Field(default_factory=list)
    prior_decisions: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class TraceEvent(BaseModel):
    step: int
    type: str  # user_request | agent_decision | tool_call | tool_result | final_answer
    title: str
    description: str
    tool: Optional[str] = None
    arguments: Optional[dict[str, Any]] = None
    result: Optional[str] = None
    timestamp: str  # ISO 8601
    status: str  # complete | error


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    answer: str
    feasible: Optional[bool] = None  # None if the model couldn't determine
    total_cost: Optional[float] = None
    budget: Optional[float] = None
    remaining: Optional[float] = None
    overage: Optional[float] = None
    currency: Optional[str] = None
    trace: list[TraceEvent] = Field(default_factory=list)


class HealthResponse(BaseModel):
    ollama_reachable: bool
    model_available: bool
    model: str
    message: str


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
