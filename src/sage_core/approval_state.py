"""Store approval-gated task proposals so models cannot mutate personal state directly."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


class ApprovalStateRepository:
    """Create and resolve approval records within one atomic SQLite transaction."""

    def __init__(self, database: SageDatabase) -> None:
        """Use the shared Sage database for approval and task state."""
        self.database = database
        self.auditStateRepository = AuditStateRepository(database)

    def createProposal(
        self, actionType: str, payload: dict[str, str | None]
    ) -> dict[str, str]:
        """Store a supported proposal without changing the associated personal state."""
        approvalId = str(uuid4())
        createdAt = datetime.now(UTC)
        expiresAt = createdAt + timedelta(hours=24)
        with self.database.connectDatabase() as connection:
            connection.execute(
                """
                INSERT INTO approval_requests (
                    id, action_type, payload_json, status, created_at, expires_at
                ) VALUES (?, ?, ?, 'PENDING', ?, ?)
                """,
                (
                    approvalId,
                    actionType,
                    json.dumps(payload),
                    createdAt.isoformat(),
                    expiresAt.isoformat(),
                ),
            )
            self.auditStateRepository.recordEvent(
                actionType=actionType,
                actor="sage-proposal-channel",
                connection=connection,
                eventStatus="PENDING",
                metadata={"approvalId": approvalId},
                targetId=approvalId,
                targetType="approval_request",
            )

        return {"id": approvalId, "status": "PENDING"}

    def confirmProposal(self, approvalId: str, approvedBy: str) -> dict[str, str]:
        """Apply one unexpired proposal in the same transaction as its approval state."""
        with self.database.connectDatabase() as connection:
            approvalRow = connection.execute(
                """
                SELECT action_type, expires_at, payload_json, status
                FROM approval_requests
                WHERE id = ?
                """,
                (approvalId,),
            ).fetchone()
            if approvalRow is None:
                raise LookupError("Approval request was not found")

            actionType, expiresAt, payloadJson, status = approvalRow
            if actionType not in {"CREATE_CASE", "CREATE_TASK", "CREATE_SCHEDULE"} or status != "PENDING":
                raise ValueError("Approval request cannot be fulfilled")
            if datetime.fromisoformat(expiresAt) <= datetime.now(UTC):
                raise TimeoutError("Approval request has expired")

            taskPayload = json.loads(payloadJson)
            connection.execute(
                """
                UPDATE approval_requests
                SET status = 'APPROVED', approved_by = ?
                WHERE id = ? AND status = 'PENDING'
                """,
                (approvedBy, approvalId),
            )
            if actionType == "CREATE_TASK":
                connection.execute(
                    """
                    INSERT INTO tasks (
                        id, title, description, status, priority, due_at, recurrence,
                        created_at, approval_request_id
                    ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        taskPayload["title"],
                        taskPayload["description"],
                        taskPayload.get("priority", "MEDIUM"),
                        taskPayload.get("dueAt"),
                        taskPayload.get("recurrence"),
                        datetime.now(UTC).isoformat(),
                        approvalId,
                    ),
                )
            elif actionType == "CREATE_CASE":
                connection.execute(
                    """
                    INSERT INTO cases (
                        id, title, objective, status, created_at, approval_request_id
                    ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
                    """,
                    (
                        str(uuid4()),
                        taskPayload["title"],
                        taskPayload["objective"],
                        datetime.now(UTC).isoformat(),
                        approvalId,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO schedules (
                        id, title, prompt, kind, status, recurrence, next_run_at,
                        created_at, approval_request_id
                    ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        taskPayload["title"],
                        taskPayload["prompt"],
                        taskPayload["kind"],
                        taskPayload.get("recurrence"),
                        taskPayload["dueAt"],
                        datetime.now(UTC).isoformat(),
                        approvalId,
                    ),
                )

            self.auditStateRepository.recordEvent(
                actionType=actionType,
                actor=approvedBy,
                connection=connection,
                eventStatus="APPROVED",
                metadata={"approvalId": approvalId},
                targetId=approvalId,
                targetType="approval_request",
            )

        return {"id": approvalId, "status": "APPROVED"}

    def declineProposal(self, approvalId: str, declinedBy: str) -> dict[str, str]:
        """Close one pending proposal without materializing the proposed personal state."""
        with self.database.connectDatabase() as connection:
            approvalRow = connection.execute(
                "SELECT action_type, expires_at, status FROM approval_requests WHERE id = ?",
                (approvalId,),
            ).fetchone()
            if approvalRow is None:
                raise LookupError("Approval request was not found")
            actionType, expiresAt, approvalStatus = approvalRow
            if approvalStatus != "PENDING":
                raise ValueError("Approval request cannot be declined")
            if datetime.fromisoformat(expiresAt) <= datetime.now(UTC):
                raise TimeoutError("Approval request has expired")
            connection.execute(
                "UPDATE approval_requests SET status = 'DECLINED', approved_by = ? WHERE id = ? AND status = 'PENDING'",
                (declinedBy, approvalId),
            )
            self.auditStateRepository.recordEvent(
                actionType=actionType,
                actor=declinedBy,
                connection=connection,
                eventStatus="DECLINED",
                metadata={"approvalId": approvalId},
                targetId=approvalId,
                targetType="approval_request",
            )
        return {"id": approvalId, "status": "DECLINED"}

    def listTasks(self) -> list[dict[str, str | None]]:
        """Return user tasks without exposing internal approval implementation details."""
        with self.database.connectDatabase() as connection:
            taskRows = connection.execute(
                """
                SELECT title, description, status, priority, due_at, recurrence
                FROM tasks
                ORDER BY created_at
                """
            ).fetchall()

        return [
            {
                "title": title,
                "description": description,
                "status": status,
                "priority": priority,
                "dueAt": dueAt,
                "recurrence": recurrence,
            }
            for title, description, status, priority, dueAt, recurrence in taskRows
        ]

    def listCases(self) -> list[dict[str, str]]:
        """Return active cases without exposing their approval implementation details."""
        with self.database.connectDatabase() as connection:
            caseRows = connection.execute(
                "SELECT title, objective, status FROM cases ORDER BY created_at"
            ).fetchall()

        return [
            {"title": title, "objective": objective, "status": status}
            for title, objective, status in caseRows
        ]

    def listAuditEvents(self) -> list[dict[str, str]]:
        """Return durable summaries of approvals handled by this state repository."""
        return self.auditStateRepository.listEvents()
