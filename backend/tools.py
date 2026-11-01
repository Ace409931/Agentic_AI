"""
LangChain tools for the Travel Budget Planner agent.

These tools are decorated with @tool so LangGraph can bind them to the
model and let the model decide when to call each one.
Docstrings are the primary tool-selection signal for small local models.
"""

import math

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Hardcoded demonstration exchange rates (not live market data).
# Extended slightly for test coverage; clearly labeled as demo-only.
# ---------------------------------------------------------------------------
EXCHANGE_RATES: dict[str, dict[str, float]] = {
    "EUR": {"INR": 95.0, "USD": 1.08, "GBP": 0.86},
    "USD": {"INR": 88.0, "EUR": 0.93, "GBP": 0.79},
    "INR": {"USD": 0.011, "EUR": 0.0105, "GBP": 0.0092},
    "GBP": {"INR": 108.5, "USD": 1.27, "EUR": 1.16},
}

SUPPORTED_CURRENCIES = list(EXCHANGE_RATES.keys())

CURRENCY_ALIASES: dict[str, str] = {
    "₹": "INR", "RS": "INR", "RS.": "INR", "RUPEES": "INR", "RUPEE": "INR", "INR": "INR",
    "€": "EUR", "EURO": "EUR", "EUROS": "EUR", "EUR": "EUR",
    "$": "USD", "DOLLAR": "USD", "DOLLARS": "USD", "USD": "USD", "US": "USD",
    "£": "GBP", "POUND": "GBP", "POUNDS": "GBP", "GBP": "GBP",
}


def _normalize_currency(curr: str) -> str:
    c = curr.strip()
    return CURRENCY_ALIASES.get(c.upper(), CURRENCY_ALIASES.get(c, c.upper()))


@tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """First-step tool: Convert an amount between currencies using demonstration exchange rates.
    MUST be called before check_budget_feasibility whenever trip cost and budget are in different currencies.
    Supported currencies: EUR (€), USD ($), INR (₹), GBP (£).

    Args:
        amount: The monetary amount to convert (must be positive).
        from_currency: Source currency code or symbol (e.g. 'EUR', '€', 'USD', '$', 'INR', '₹', 'GBP', '£').
        to_currency: Target currency code or symbol (e.g. 'INR', '₹', 'EUR', '€', 'USD', '$', 'GBP', '£').

    Returns:
        A human-readable sentence with the converted amount and the rate used.
    """
    from_currency = _normalize_currency(from_currency)
    to_currency = _normalize_currency(to_currency)

    if not math.isfinite(amount) or amount <= 0:
        return (
            f"Validation error: amount must be a finite number greater than zero, got {amount}. "
            "Please provide a positive monetary amount."
        )

    if from_currency not in EXCHANGE_RATES:
        return (
            f"Unsupported currency: {from_currency}. "
            f"Supported currencies: {', '.join(SUPPORTED_CURRENCIES)}."
        )

    if to_currency not in EXCHANGE_RATES:
        return (
            f"Unsupported currency: {to_currency}. "
            f"Supported currencies: {', '.join(SUPPORTED_CURRENCIES)}."
        )

    if from_currency == to_currency:
        return (
            f"No conversion needed: {amount} {from_currency} is already in "
            f"{to_currency}. Amount remains {amount}."
        )

    if to_currency not in EXCHANGE_RATES.get(from_currency, {}):
        return (
            f"No demonstration exchange rate is available from {from_currency} "
            f"to {to_currency}."
        )

    rate = EXCHANGE_RATES[from_currency][to_currency]
    converted_amount = amount * rate
    if not math.isfinite(converted_amount):
        return "Validation error: the converted amount is too large to represent."
    converted = round(converted_amount, 2)

    return (
        f"Converted {amount} {from_currency} to {converted} {to_currency} "
        f"using the demonstration rate 1 {from_currency} = {rate} {to_currency}."
    )


@tool
def check_budget_feasibility(total_cost: float, cost_currency: str, budget: float, budget_currency: str) -> str:
    """Compare a total trip cost against a budget and report whether the trip is feasible.
    Currencies MUST match before calling this tool. If they don't match, you must use convert_currency first.

    Args:
        total_cost: The total cost of the trip.
        cost_currency: The currency of the total cost (e.g. 'EUR', 'INR').
        budget: The available budget.
        budget_currency: The currency of the budget (e.g. 'EUR', 'INR').

    Returns:
        A human-readable sentence stating feasibility, or an error if currencies don't match.
    """
    cost_curr = _normalize_currency(cost_currency)
    budg_curr = _normalize_currency(budget_currency)

    if (
        not math.isfinite(total_cost)
        or not math.isfinite(budget)
        or total_cost < 0
        or budget < 0
    ):
        return (
            f"Validation error: total_cost ({total_cost}) and budget ({budget}) "
            "must be finite, non-negative amounts."
        )

    unsupported = [
        currency for currency in (cost_curr, budg_curr)
        if currency not in EXCHANGE_RATES
    ]
    if unsupported:
        return (
            f"Unsupported currency: {unsupported[0]}. "
            f"Supported currencies: {', '.join(SUPPORTED_CURRENCIES)}."
        )

    if cost_curr != budg_curr:
        return (
            f"Error: Currencies do not match (Cost: {cost_curr}, Budget: {budg_curr}). "
            "You MUST call `convert_currency` first to convert the trip cost to the budget currency, "
            "and then call this tool again with the converted amount and matching currencies."
        )

    if total_cost <= budget:
        remaining = round(budget - total_cost, 2)
        return (
            f"Trip is feasible. Total cost is {total_cost} {cost_curr} and the budget is {budget} {budg_curr}. "
            f"Remaining budget: {remaining} {budg_curr}."
        )
    else:
        overage = round(total_cost - budget, 2)
        return (
            f"Trip is NOT feasible. Total cost is {total_cost} {cost_curr} but the budget is {budget} {budg_curr}. "
            f"Over budget by {overage} {budg_curr}."
        )
