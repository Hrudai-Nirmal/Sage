"""Persist retryable Gmail and Calendar mutations outside model execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


class GoogleActionRepository:
    """Own the durable outbox for explicit or independently approved Google actions."""

    def __init__(self, database: SageDatabase) -> None:
        """Bind the outbox to Sage's shared database."""
        self.database = database
        self.auditStateRepository = AuditStateRepository(database)

    def queueAction(
        self,
        actionType: str,
        accountKey: str,
        payload: dict[str, object],
        idempotencyKey: str,
        approvalRequestId: str | None = None,
    ) -> dict[str, str]:
        """Queue one validated action while deduplicating retries of the same intent."""
        supportedActions = {
            "CREATE_CALENDAR_EVENT",
            "DELETE_CALENDAR_EVENT",
            "SEND_GMAIL_MESSAGE",
            "UPDATE_CALENDAR_EVENT",
        }
        if actionType not in supportedActions:
            raise ValueError("Unsupported Google action")
        if accountKey not in {"personal-work", "work", "personal", "college"}:
            raise ValueError("Google action account is not configured")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("Google action payload is required")
        if not isinstance(idempotencyKey, str) or not idempotencyKey.strip():
            raise ValueError("Google action idempotency key is required")
        actionId = str(uuid4())
        actionStage = "CREATE_DRAFT" if actionType == "SEND_GMAIL_MESSAGE" else "EXECUTE"
        queuedAt = datetime.now(UTC).isoformat()
        with self.database.connectDatabase() as connection:
            insertResult = connection.execute(
                """INSERT OR IGNORE INTO google_actions (
                       id, idempotency_key, action_type, account_key, payload_json,
                       stage, status, next_attempt_at, approval_request_id
                   ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
                (
                    actionId,
                    idempotencyKey.strip(),
                    actionType,
                    accountKey,
                    json.dumps(payload, sort_keys=True),
                    actionStage,
                    queuedAt,
                    approvalRequestId,
                ),
            )
            if insertResult.rowcount == 1:
                self.auditStateRepository.recordEvent(
                    connection=connection,
                    actor="sage:google-action-router",
                    actionType=actionType,
                    targetType="GOOGLE_ACTION",
                    targetId=actionId,
                    eventStatus="PENDING",
                    metadata={"accountKey": accountKey},
                )
            actionRow = connection.execute(
                "SELECT id, status FROM google_actions WHERE idempotency_key = ?",
                (idempotencyKey.strip(),),
            ).fetchone()
        if actionRow is None:
            raise RuntimeError("Google action could not be queued")
        return {"id": str(actionRow[0]), "status": str(actionRow[1])}

    def claimPendingAction(self, now: datetime | None = None) -> dict[str, object] | None:
        """Atomically claim the oldest due Google action."""
        currentTime = now or datetime.now(UTC)
        if currentTime.tzinfo is None:
            raise ValueError("Google action time must include a timezone")
        with self.database.connectDatabase() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actionRow = connection.execute(
                """SELECT id, action_type, account_key, payload_json, stage, remote_id
                   FROM google_actions
                   WHERE status = 'PENDING' AND julianday(next_attempt_at) <= julianday(?)
                   ORDER BY next_attempt_at, id LIMIT 1""",
                (currentTime.isoformat(),),
            ).fetchone()
            if actionRow is None:
                return None
            connection.execute(
                "UPDATE google_actions SET status = 'PROCESSING' WHERE id = ?",
                (actionRow[0],),
            )
        return {
            "id": str(actionRow[0]),
            "actionType": str(actionRow[1]),
            "accountKey": str(actionRow[2]),
            "payload": json.loads(str(actionRow[3])),
            "stage": str(actionRow[4]),
            "remoteId": str(actionRow[5] or ""),
        }

    def stageGmailDraft(self, actionId: str, draftId: str) -> None:
        """Persist the remote draft before making the separately retryable send call."""
        if not draftId.strip():
            raise ValueError("Gmail draft ID is required")
        with self.database.connectDatabase() as connection:
            updateResult = connection.execute(
                """UPDATE google_actions
                   SET stage = 'SEND_DRAFT', status = 'PENDING', remote_id = ?,
                       attempts = 0, next_attempt_at = ?, error_type = NULL
                   WHERE id = ? AND action_type = 'SEND_GMAIL_MESSAGE'
                     AND stage = 'CREATE_DRAFT' AND status = 'PROCESSING'""",
                (draftId.strip(), datetime.now(UTC).isoformat(), actionId),
            )
            if updateResult.rowcount != 1:
                raise LookupError("Processing Gmail draft action was not found")

    def completeAction(
        self, actionId: str, remoteId: str = "", completedAt: datetime | None = None
    ) -> None:
        """Complete an action only after Google accepts its current stage."""
        completionTime = completedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            actionRow = connection.execute(
                "SELECT action_type FROM google_actions WHERE id = ? AND status = 'PROCESSING'",
                (actionId,),
            ).fetchone()
            if actionRow is None:
                raise LookupError("Processing Google action was not found")
            connection.execute(
                """UPDATE google_actions SET status = 'COMPLETE', completed_at = ?,
                          remote_id = CASE WHEN ? = '' THEN remote_id ELSE ? END
                   WHERE id = ? AND status = 'PROCESSING'""",
                (completionTime.isoformat(), remoteId, remoteId, actionId),
            )
            self.auditStateRepository.recordEvent(
                connection=connection,
                actor="sage:google-action-worker",
                actionType=str(actionRow[0]),
                targetType="GOOGLE_ACTION",
                targetId=actionId,
                eventStatus="COMPLETE",
                metadata={"remoteId": remoteId},
            )

    def failAction(
        self, actionId: str, errorType: str, failedAt: datetime | None = None
    ) -> None:
        """Return a failed action to the outbox with bounded exponential backoff."""
        failureTime = failedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            attemptsRow = connection.execute(
                "SELECT attempts FROM google_actions WHERE id = ? AND status = 'PROCESSING'",
                (actionId,),
            ).fetchone()
            if attemptsRow is None:
                raise LookupError("Processing Google action was not found")
            attempts = int(attemptsRow[0]) + 1
            retryAt = failureTime + timedelta(minutes=min(2**attempts, 60))
            connection.execute(
                """UPDATE google_actions SET status = 'PENDING', attempts = ?,
                          next_attempt_at = ?, error_type = ? WHERE id = ?""",
                (attempts, retryAt.isoformat(), errorType[:200], actionId),
            )

    def quarantinePendingAction(self, actionId: str, reasonCode: str) -> None:
        """Keep a known-invalid action for audit while making it ineligible for delivery."""
        if not isinstance(actionId, str) or not actionId.strip():
            raise ValueError("Google action ID is required")
        if not isinstance(reasonCode, str) or not reasonCode.strip():
            raise ValueError("Google action quarantine reason is required")
        normalizedReason = reasonCode.strip()[:200]
        with self.database.connectDatabase() as connection:
            actionRow = connection.execute(
                "SELECT action_type FROM google_actions WHERE id = ? AND status = 'PENDING'",
                (actionId.strip(),),
            ).fetchone()
            if actionRow is None:
                raise LookupError("Pending Google action was not found")
            connection.execute(
                "UPDATE google_actions SET status = 'QUARANTINED', error_type = ? WHERE id = ?",
                (normalizedReason, actionId.strip()),
            )
            self.auditStateRepository.recordEvent(
                connection=connection,
                actor="sage:safety-guard",
                actionType=str(actionRow[0]),
                targetType="GOOGLE_ACTION",
                targetId=actionId.strip(),
                eventStatus="QUARANTINED",
                metadata={"reason": normalizedReason},
            )

    def recoverInterruptedActions(self) -> None:
        """Return actions interrupted by a restart to their current durable stage."""
        with self.database.connectDatabase() as connection:
            connection.execute(
                "UPDATE google_actions SET status = 'PENDING' WHERE status = 'PROCESSING'"
            )
