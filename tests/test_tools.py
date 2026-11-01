"""
Unit tests for travel budget planner tools.
No Ollama required — tests pure Python logic only.
"""

import sys
import os
import math

import pytest
from pydantic import ValidationError

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.tools import convert_currency, check_budget_feasibility


# ---------------------------------------------------------------------------
# convert_currency tests
# ---------------------------------------------------------------------------


def test_eur_to_inr_amount():
    """900 EUR → 85500 INR (rate 95.0)."""
    result = convert_currency.invoke({"amount": 900, "from_currency": "EUR", "to_currency": "INR"})
    assert "85500.0" in result


def test_eur_to_inr_sentence():
    """Result should be a human-readable sentence the LLM can quote."""
    result = convert_currency.invoke({"amount": 900, "from_currency": "EUR", "to_currency": "INR"})
    assert "EUR" in result
    assert "INR" in result
    assert "95.0" in result


def test_usd_to_inr():
    result = convert_currency.invoke({"amount": 100, "from_currency": "USD", "to_currency": "INR"})
    assert "8800.0" in result


def test_same_currency():
    result = convert_currency.invoke({"amount": 500, "from_currency": "INR", "to_currency": "INR"})
    assert "No conversion needed" in result or "500" in result


def test_unsupported_from_currency():
    result = convert_currency.invoke({"amount": 100, "from_currency": "JPY", "to_currency": "INR"})
    assert "Unsupported" in result
    assert "JPY" in result
    assert "EUR" in result  # should list supported currencies


def test_unsupported_to_currency():
    result = convert_currency.invoke({"amount": 100, "from_currency": "USD", "to_currency": "JPY"})
    assert "Unsupported" in result
    assert "JPY" in result


def test_unsupported_same_currency_is_not_treated_as_no_conversion():
    result = convert_currency.invoke({
        "amount": 100,
        "from_currency": "JPY",
        "to_currency": "JPY",
    })
    assert "Unsupported currency: JPY" in result


def test_negative_amount():
    result = convert_currency.invoke({"amount": -50, "from_currency": "EUR", "to_currency": "INR"})
    assert "Validation error" in result or "must be greater than zero" in result.lower() or "greater than zero" in result


def test_zero_amount():
    result = convert_currency.invoke({"amount": 0, "from_currency": "EUR", "to_currency": "INR"})
    assert "Validation error" in result or "greater than zero" in result.lower()


def test_case_insensitive_currency():
    """Currency codes should be case-insensitive."""
    result = convert_currency.invoke({"amount": 900, "from_currency": "eur", "to_currency": "inr"})
    assert "85500.0" in result


# ---------------------------------------------------------------------------
# check_budget_feasibility tests
# ---------------------------------------------------------------------------


def test_feasible_case():
    """85500 cost vs 100000 budget → feasible, 14500 remaining."""
    result = check_budget_feasibility.invoke({
        "total_cost": 85500,
        "cost_currency": "INR",
        "budget": 100000,
        "budget_currency": "INR",
    })
    assert "feasible" in result.lower()
    assert "14500.0" in result
    assert "NOT" not in result


def test_not_feasible_case():
    """85500 cost vs 50000 budget → not feasible, overage 35500."""
    result = check_budget_feasibility.invoke({
        "total_cost": 85500,
        "cost_currency": "INR",
        "budget": 50000,
        "budget_currency": "INR",
    })
    assert "NOT feasible" in result
    assert "35500.0" in result


def test_exact_budget():
    """Cost equals budget exactly → feasible with 0 remaining."""
    result = check_budget_feasibility.invoke({
        "total_cost": 100000,
        "cost_currency": "INR",
        "budget": 100000,
        "budget_currency": "INR",
    })
    assert "feasible" in result.lower()
    assert "NOT" not in result


def test_negative_cost():
    result = check_budget_feasibility.invoke({
        "total_cost": -100,
        "cost_currency": "INR",
        "budget": 50000,
        "budget_currency": "INR",
    })
    assert "Validation error" in result or "non-negative" in result.lower()


def test_negative_budget():
    result = check_budget_feasibility.invoke({
        "total_cost": 50000,
        "cost_currency": "INR",
        "budget": -100,
        "budget_currency": "INR",
    })
    assert "Validation error" in result or "non-negative" in result.lower()


def test_returns_string_not_exception():
    """Tools must return error strings, not raise, on bad input."""
    try:
        r1 = convert_currency.invoke({"amount": -1, "from_currency": "EUR", "to_currency": "INR"})
        assert isinstance(r1, str)
        r2 = check_budget_feasibility.invoke({
            "total_cost": -1,
            "cost_currency": "INR",
            "budget": -1,
            "budget_currency": "INR",
        })
        assert isinstance(r2, str)
    except Exception as e:
        raise AssertionError(f"Tool raised instead of returning an error string: {e}")


def test_different_budget_currencies_are_rejected():
    result = check_budget_feasibility.invoke({
        "total_cost": 900,
        "cost_currency": "EUR",
        "budget": 100000,
        "budget_currency": "INR",
    })
    assert "Currencies do not match" in result
    assert "convert_currency" in result


def test_unsupported_matching_currency_is_rejected():
    result = check_budget_feasibility.invoke({
        "total_cost": 100,
        "cost_currency": "JPY",
        "budget": 200,
        "budget_currency": "JPY",
    })
    assert "Unsupported currency: JPY" in result


def test_non_finite_amounts_are_rejected():
    result = check_budget_feasibility.invoke({
        "total_cost": math.inf,
        "cost_currency": "INR",
        "budget": 200,
        "budget_currency": "INR",
    })
    assert "finite" in result

    converted = convert_currency.invoke({
        "amount": math.nan,
        "from_currency": "EUR",
        "to_currency": "INR",
    })
    assert "finite" in converted


def test_unrepresentably_large_conversion_is_rejected():
    result = convert_currency.invoke({
        "amount": 1e308,
        "from_currency": "EUR",
        "to_currency": "INR",
    })
    assert "too large to represent" in result


def test_missing_currency_arguments_are_validation_errors():
    with pytest.raises(ValidationError):
        check_budget_feasibility.invoke({"total_cost": 10, "budget": 20})
