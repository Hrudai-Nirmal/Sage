"""Persist schedules and their retryable delivery backlog independently of process uptime."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


class ScheduleStateRepository:
    """Own schedule recurrence, due-run materialization, and delivery retries."""

    def __init__(self, database: SageDatabase) -> None:
        """Use the shared durable database for schedules and audit events."""
        self.database = database
        self.auditStateRepository = AuditStateRepository(database)

    def createSchedule(
        self,
        approvalRequestId: str,
        dueAt: str,
        kind: str,
        prompt: str,
        recurrence: str | None,
        title: str,
    ) -> dict[str, str | None]:
        """Create one approved schedule after validating its deterministic cadence."""
        if kind not in {"REPORT", "NOTIFICATION"}:
            raise ValueError("Schedule kind must be REPORT or NOTIFICATION")
        if recurrence not in {None, "DAILY", "WEEKLY"}:
            raise ValueError("Schedule recurrence must be DAILY, WEEKLY, or omitted")
        dueTimestamp = datetime.fromisoformat(dueAt)
        if dueTimestamp.tzinfo is None:
            raise ValueError("Schedule dueAt must include a timezone")
        if not title.strip() or not prompt.strip():
            raise ValueError("Schedule title and prompt are required")
        scheduleId = str(uuid4())
        with self.database.connectDatabase() as connection:
            connection.execute(
                """INSERT INTO schedules (
                    id, title, prompt, kind, status, recurrence, next_run_at,
                    created_at, approval_request_id
                ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)""",
                (
                    scheduleId,
                    title.strip(),
                    prompt.strip(),
                    kind,
                    recurrence,
                    dueAt,
                    datetime.now(UTC).isoformat(),
                    approvalRequestId,
                ),
            )
            self.auditStateRepository.recordEvent(
                connection=connection,
                actor="sage:scheduler",
                actionType="CREATE_SCHEDULE",
                targetType="SCHEDULE",
                targetId=scheduleId,
                eventStatus="APPROVED",
                metadata={"kind": kind},
            )
        return {"id": scheduleId, "nextRunAt": dueAt, "status": "ACTIVE"}

    def claimDueDelivery(self, now: datetime | None = None) -> dict[str, str] | None:
        """Atomically claim one retry or materialize the oldest missed schedule run."""
        currentTime = now or datetime.now(UTC)
        if currentTime.tzinfo is None:
            raise ValueError("Scheduler time must include a timezone")
        currentIso = currentTime.isoformat()
        with self.database.connectDatabase() as connection:
            connection.execute("BEGIN IMMEDIATE")
            dueSchedule = connection.execute(
                """SELECT id, next_run_at FROM schedules
                   WHERE status = 'ACTIVE' AND next_run_at IS NOT NULL
                     AND julianday(next_run_at) <= julianday(?)
                   ORDER BY next_run_at, id LIMIT 1""",
                (currentIso,),
            ).fetchone()
            if dueSchedule is not None:
                scheduleId, dueAt = dueSchedule
                connection.execute(
                    """INSERT OR IGNORE INTO scheduled_deliveries (
                        id, schedule_id, due_at, status, next_attempt_at
                    ) VALUES (?, ?, ?, 'PENDING', ?)""",
                    (str(uuid4()), scheduleId, dueAt, dueAt),
                )
            deliveryRow = connection.execute(
                """SELECT d.id, d.schedule_id, d.due_at, s.kind, s.prompt, s.title
                   FROM scheduled_deliveries d JOIN schedules s ON s.id = d.schedule_id
                   WHERE d.status = 'PENDING'
                     AND julianday(d.next_attempt_at) <= julianday(?)
                   ORDER BY d.due_at, d.id LIMIT 1""",
                (currentIso,),
            ).fetchone()
            if deliveryRow is None:
                return None
            connection.execute(
                "UPDATE scheduled_deliveries SET status = 'PROCESSING' WHERE id = ?",
                (deliveryRow[0],),
            )
        deliveryId, scheduleId, dueAt, kind, prompt, title = deliveryRow
        return {
            "dueAt": dueAt,
            "id": deliveryId,
            "kind": kind,
            "prompt": prompt,
            "scheduleId": scheduleId,
            "title": title,
        }

    def completeDelivery(self, deliveryId: str, completedAt: datetime | None = None) -> None:
        """Complete one delivery and advance recurrence from its original due timestamp."""
        completionTime = completedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            deliveryRow = connection.execute(
                """SELECT d.schedule_id, d.due_at, s.recurrence
                   FROM scheduled_deliveries d JOIN schedules s ON s.id = d.schedule_id
                   WHERE d.id = ? AND d.status = 'PROCESSING'""",
                (deliveryId,),
            ).fetchone()
            if deliveryRow is None:
                raise LookupError("Processing delivery was not found")
            scheduleId, dueAt, recurrence = deliveryRow
            connection.execute(
                "UPDATE scheduled_deliveries SET status = 'COMPLETE', completed_at = ? WHERE id = ?",
                (completionTime.isoformat(), deliveryId),
            )
            if recurrence is None:
                connection.execute(
                    "UPDATE schedules SET status = 'COMPLETE', next_run_at = NULL WHERE id = ?",
                    (scheduleId,),
                )
            else:
                cadence = timedelta(days=1 if recurrence == "DAILY" else 7)
                nextRunAt = (datetime.fromisoformat(dueAt) + cadence).isoformat()
                connection.execute(
                    "UPDATE schedules SET next_run_at = ? WHERE id = ?",
                    (nextRunAt, scheduleId),
                )

    def failDelivery(self, deliveryId: str, errorType: str, failedAt: datetime | None = None) -> None:
        """Return one failed claim to its backlog with bounded exponential delay."""
        failureTime = failedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            attemptsRow = connection.execute(
                "SELECT attempts FROM scheduled_deliveries WHERE id = ? AND status = 'PROCESSING'",
                (deliveryId,),
            ).fetchone()
            if attemptsRow is None:
                raise LookupError("Processing delivery was not found")
            attempts = int(attemptsRow[0]) + 1
            retryDelay = timedelta(minutes=min(2**attempts, 60))
            connection.execute(
                """UPDATE scheduled_deliveries
                   SET status = 'PENDING', attempts = ?, next_attempt_at = ?, error_type = ?
                   WHERE id = ?""",
                (attempts, (failureTime + retryDelay).isoformat(), errorType[:200], deliveryId),
            )

    def recoverInterruptedDeliveries(self) -> None:
        """Return deliveries abandoned during shutdown to the durable retry queue."""
        with self.database.connectDatabase() as connection:
            connection.execute(
                "UPDATE scheduled_deliveries SET status = 'PENDING' WHERE status = 'PROCESSING'"
            )

    def listSchedules(self) -> list[dict[str, str | None]]:
        """List schedules for Telegram and the local operator interface."""
        with self.database.connectDatabase() as connection:
            rows = connection.execute(
                "SELECT id, title, kind, status, recurrence, next_run_at FROM schedules ORDER BY created_at"
            ).fetchall()
        return [
            {
                "id": scheduleId,
                "kind": kind,
                "nextRunAt": nextRunAt,
                "recurrence": recurrence,
                "status": status,
                "title": title,
            }
            for scheduleId, title, kind, status, recurrence, nextRunAt in rows
        ]

    def getDeliveryStatus(self, deliveryId: str) -> dict[str, int | str]:
        """Expose retry state for tests and operator diagnostics."""
        with self.database.connectDatabase() as connection:
            row = connection.execute(
                "SELECT status, attempts FROM scheduled_deliveries WHERE id = ?", (deliveryId,)
            ).fetchone()
        if row is None:
            raise LookupError("Delivery was not found")
        return {"attempts": int(row[1]), "status": str(row[0])}
