"""Claim and retry Google Drive mutations created through independent approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


class DriveActionRepository:
    """Own approved Drive mutation delivery state."""

    def __init__(self, database: SageDatabase) -> None:
        """Bind the action queue to Sage's shared database."""
        self.database = database
        self.auditStateRepository = AuditStateRepository(database)

    def claimPendingAction(self, now: datetime | None = None) -> dict[str, str] | None:
        """Atomically claim the oldest approved Drive action due for execution."""
        currentTime = now or datetime.now(UTC)
        if currentTime.tzinfo is None:
            raise ValueError("Drive action time must include a timezone")
        with self.database.connectDatabase() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actionRow = connection.execute(
                """SELECT id, action_type, account_key, file_id, name FROM drive_actions
                   WHERE status = 'PENDING' AND julianday(next_attempt_at) <= julianday(?)
                   ORDER BY next_attempt_at, id LIMIT 1""",
                (currentTime.isoformat(),),
            ).fetchone()
            if actionRow is None:
                return None
            connection.execute(
                "UPDATE drive_actions SET status = 'PROCESSING' WHERE id = ?",
                (actionRow[0],),
            )
        return {
            "id": str(actionRow[0]),
            "actionType": str(actionRow[1]),
            "accountKey": str(actionRow[2]),
            "fileId": str(actionRow[3]),
            "name": str(actionRow[4]),
        }

    def completeAction(self, actionId: str, completedAt: datetime | None = None) -> None:
        """Complete one Drive action only after Google accepts it."""
        completionTime = completedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            updateResult = connection.execute(
                """UPDATE drive_actions SET status = 'COMPLETE', completed_at = ?
                   WHERE id = ? AND status = 'PROCESSING'""",
                (completionTime.isoformat(), actionId),
            )
            if updateResult.rowcount != 1:
                raise LookupError("Processing Drive action was not found")
            self.auditStateRepository.recordEvent(
                connection=connection,
                actor="sage:drive-worker",
                actionType="DELETE_DRIVE_FILE",
                targetType="DRIVE_FILE",
                targetId=actionId,
                eventStatus="COMPLETE",
                metadata={"approvedActionId": actionId},
            )

    def failAction(
        self, actionId: str, errorType: str, failedAt: datetime | None = None
    ) -> None:
        """Return a failed Drive action to the durable retry queue."""
        failureTime = failedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            attemptsRow = connection.execute(
                "SELECT attempts FROM drive_actions WHERE id = ? AND status = 'PROCESSING'",
                (actionId,),
            ).fetchone()
            if attemptsRow is None:
                raise LookupError("Processing Drive action was not found")
            attempts = int(attemptsRow[0]) + 1
            retryAt = failureTime + timedelta(minutes=min(2**attempts, 60))
            connection.execute(
                """UPDATE drive_actions SET status = 'PENDING', attempts = ?,
                          next_attempt_at = ?, error_type = ? WHERE id = ?""",
                (attempts, retryAt.isoformat(), errorType[:200], actionId),
            )

    def recoverInterruptedActions(self) -> None:
        """Return an interrupted approved mutation to its queue after restart."""
        with self.database.connectDatabase() as connection:
            connection.execute(
                "UPDATE drive_actions SET status = 'PENDING' WHERE status = 'PROCESSING'"
            )
