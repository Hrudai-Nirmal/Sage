"""Record durable, reviewable evidence of Sage actions independently of n8n history."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from sage_core.database import SageDatabase


class AuditStateRepository:
    """Write audit events within callers' transactions and expose safe event summaries."""

    def __init__(self, database: SageDatabase) -> None:
        """Use the shared Sage database for durable audit history."""
        self.database = database

    def recordEvent(
        self,
        connection: sqlite3.Connection,
        actor: str,
        actionType: str,
        targetType: str,
        targetId: str,
        eventStatus: str,
        metadata: dict[str, str],
    ) -> None:
        """Persist an event atomically with the state transition it documents."""
        connection.execute(
            """
            INSERT INTO audit_events (
                id, timestamp, actor, action_type, target_type, target_id, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                datetime.now(UTC).isoformat(),
                actor,
                actionType,
                targetType,
                targetId,
                eventStatus,
                json.dumps(metadata),
            ),
        )

    def listEvents(self) -> list[dict[str, str]]:
        """Return auditable action summaries without exposing sensitive payload data."""
        with self.database.connectDatabase() as connection:
            eventRows = connection.execute(
                """
                SELECT actor, action_type, status
                FROM audit_events
                ORDER BY timestamp, id
                """
            ).fetchall()

        return [
            {"actor": actor, "actionType": actionType, "status": eventStatus}
            for actor, actionType, eventStatus in eventRows
        ]
