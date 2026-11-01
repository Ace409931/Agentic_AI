"""Small SQLite stores for trip preferences and thread-independent metadata."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DATABASE_PATH
from .models import TripPreferences


class TripStore:
    def __init__(self, database_path: Path | str = DATABASE_PATH):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_preferences (
                    trip_id TEXT PRIMARY KEY,
                    preferences_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_conversations (
                    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save_preferences(self, trip_id: str, preferences: TripPreferences) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO trip_preferences (trip_id, preferences_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(trip_id) DO UPDATE SET
                    preferences_json = excluded.preferences_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (trip_id, json.dumps(preferences.model_dump(mode="json"))),
            )

    def get_preferences(self, trip_id: str) -> TripPreferences | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT preferences_json FROM trip_preferences WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()
        if row is None:
            return None
        return TripPreferences.model_validate(json.loads(row["preferences_json"]))

    def append_conversation(self, trip_id: str, user_message: str, assistant_message: str) -> None:
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO trip_conversations (trip_id, role, content) VALUES (?, ?, ?)",
                [
                    (trip_id, "user", user_message),
                    (trip_id, "assistant", assistant_message),
                ],
            )

    def get_conversation(self, trip_id: str) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM trip_conversations WHERE trip_id = ? ORDER BY turn_id",
                (trip_id,),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]
