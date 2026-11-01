"""SQLite-backed LangGraph supervisor checkpoint persistence and isolation."""

from datetime import date

import pytest

from backend.models import TripPreferences
from backend import supervisor


@pytest.fixture
def trip_preferences():
    return TripPreferences(
        destination="Goa",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
        travelers=2,
        budget=30000,
        currency="INR",
        budget_style="moderate",
    )


def test_thread_memory_persists_and_isolated_between_threads(
    tmp_path, monkeypatch, trip_preferences
):
    monkeypatch.setattr(supervisor, "DATABASE_PATH", tmp_path / "threads.sqlite3")

    first = supervisor.run_planning_thread(
        "thread-a", "Plan this trip", trip_preferences
    )
    follow_up = supervisor.run_planning_thread(
        "thread-a", "Reduce my budget to ₹15,000", first.preferences
    )
    independent = supervisor.run_planning_thread(
        "thread-b", "Plan this trip", trip_preferences
    )
    restored = supervisor.get_saved_plan("thread-a")

    assert follow_up.preferences.budget == 15000
    assert restored is not None
    assert restored.preferences.budget == 15000
    assert len(restored.conversation) >= 3
    assert len(restored.prior_decisions) == 1
    assert restored.prior_decisions[0]["selected_bid"]["bid_id"] == "budget-agent"
    assert independent.preferences.budget == 30000
    assert independent.trip_id == "thread-b"
