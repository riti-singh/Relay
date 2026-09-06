from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

from relay.domain.models import Incident


class IncidentRepository(Protocol):
    def save(self, incident: Incident) -> None: ...
    def get(self, incident_id: UUID) -> Incident | None: ...
    def list(self) -> list[Incident]: ...


class SQLiteIncidentRepository:
    """Stores an incident aggregate as JSON while retaining queryable identity/timestamps."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    def save(self, incident: Incident) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT INTO incidents (id, status, created_at, updated_at, payload)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                 updated_at=excluded.updated_at, payload=excluded.payload""",
                (
                    str(incident.id),
                    incident.status.value,
                    incident.created_at.isoformat(),
                    incident.updated_at.isoformat(),
                    incident.model_dump_json(),
                ),
            )
            self._connection.commit()

    def get(self, incident_id: UUID) -> Incident | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM incidents WHERE id = ?", (str(incident_id),)
            ).fetchone()
        return Incident.model_validate_json(row["payload"]) if row else None

    def list(self) -> list[Incident]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM incidents ORDER BY created_at DESC"
            ).fetchall()
        return [Incident.model_validate_json(row["payload"]) for row in rows]
