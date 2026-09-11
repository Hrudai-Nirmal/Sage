"""Persist deterministic Calendar reminders and conservative email triage work."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sage_core.database import SageDatabase


class GoogleJobRepository:
    """Own Google-derived background jobs without creating another worker process."""

    def __init__(self, database: SageDatabase) -> None:
        """Bind jobs to Sage's shared durable database."""
        self.database = database

    def scheduleCalendarReminder(self, calendarEvent: dict[str, object]) -> None:
        """Replace a pending reminder with the event's latest confirmed timing."""
        accountKey = str(calendarEvent["accountKey"])
        eventId = str(calendarEvent["eventId"])
        eventStatus = str(calendarEvent["status"]).casefold()
        startAt = str(calendarEvent["startAt"])
        with self.database.connectDatabase() as connection:
            if eventStatus == "cancelled":
                connection.execute(
                    "DELETE FROM calendar_reminders WHERE account_key = ? AND event_id = ? AND status != 'COMPLETE'",
                    (accountKey, eventId),
                )
                return
            startTime = datetime.fromisoformat(startAt.replace("Z", "+00:00"))
            if startTime.tzinfo is None:
                return
            dueAt = (startTime - timedelta(minutes=10)).isoformat()
            summary = str(calendarEvent["summary"]).strip() or "Untitled event"
            location = str(calendarEvent["location"]).strip()
            reminderText = f"Upcoming in 10 minutes: {summary}\nStarts: {startAt}"
            if location:
                reminderText += f"\nLocation: {location}"
            connection.execute(
                """INSERT INTO calendar_reminders (
                       account_key, event_id, event_updated_at, due_at, text,
                       status, next_attempt_at
                   ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                   ON CONFLICT(account_key, event_id) DO UPDATE SET
                       event_updated_at = excluded.event_updated_at,
                       due_at = excluded.due_at,
                       text = excluded.text,
                       status = CASE
                           WHEN calendar_reminders.event_updated_at = excluded.event_updated_at
                           THEN calendar_reminders.status ELSE 'PENDING' END,
                       attempts = CASE
                           WHEN calendar_reminders.event_updated_at = excluded.event_updated_at
                           THEN calendar_reminders.attempts ELSE 0 END,
                       next_attempt_at = CASE
                           WHEN calendar_reminders.event_updated_at = excluded.event_updated_at
                           THEN calendar_reminders.next_attempt_at ELSE excluded.next_attempt_at END,
                       error_type = NULL,
                       completed_at = CASE
                           WHEN calendar_reminders.event_updated_at = excluded.event_updated_at
                           THEN calendar_reminders.completed_at ELSE NULL END""",
                (
                    accountKey,
                    eventId,
                    str(calendarEvent["updatedAt"]),
                    dueAt,
                    reminderText,
                    dueAt,
                ),
            )

    def backfillCalendarReminders(self, now: datetime | None = None) -> int:
        """Create missing reminders for upcoming events indexed before this feature."""
        currentTime = now or datetime.now(UTC)
        if currentTime.tzinfo is None:
            raise ValueError("Reminder backfill time must include a timezone")
        with self.database.connectDatabase() as connection:
            eventRows = connection.execute(
                """SELECT account_key, event_id, summary, location, status, start_at,
                          updated_at FROM calendar_events
                   WHERE status != 'cancelled' AND julianday(start_at) > julianday(?)
                     AND NOT EXISTS (
                         SELECT 1 FROM calendar_reminders r
                         WHERE r.account_key = calendar_events.account_key
                           AND r.event_id = calendar_events.event_id
                     )""",
                (currentTime.isoformat(),),
            ).fetchall()
        for accountKey, eventId, summary, location, eventStatus, startAt, updatedAt in eventRows:
            self.scheduleCalendarReminder(
                {
                    "accountKey": accountKey,
                    "eventId": eventId,
                    "summary": summary,
                    "location": location,
                    "status": eventStatus,
                    "startAt": startAt,
                    "updatedAt": updatedAt,
                }
            )
        return len(eventRows)

    def claimDueCalendarReminder(self, now: datetime | None = None) -> dict[str, str] | None:
        """Atomically claim the oldest due reminder for Telegram delivery."""
        currentTime = now or datetime.now(UTC)
        if currentTime.tzinfo is None:
            raise ValueError("Reminder time must include a timezone")
        with self.database.connectDatabase() as connection:
            connection.execute("BEGIN IMMEDIATE")
            reminderRow = connection.execute(
                """SELECT account_key, event_id, due_at, text FROM calendar_reminders
                   WHERE status = 'PENDING' AND julianday(next_attempt_at) <= julianday(?)
                   ORDER BY due_at, account_key, event_id LIMIT 1""",
                (currentTime.isoformat(),),
            ).fetchone()
            if reminderRow is None:
                return None
            connection.execute(
                "UPDATE calendar_reminders SET status = 'PROCESSING' WHERE account_key = ? AND event_id = ?",
                (reminderRow[0], reminderRow[1]),
            )
        return {
            "accountKey": str(reminderRow[0]),
            "eventId": str(reminderRow[1]),
            "dueAt": str(reminderRow[2]),
            "text": str(reminderRow[3]),
        }

    def completeCalendarReminder(
        self, accountKey: str, eventId: str, completedAt: datetime | None = None
    ) -> None:
        """Mark a processing reminder complete after Telegram accepts it."""
        self._completeJob(
            tableName="calendar_reminders",
            accountKey=accountKey,
            itemColumn="event_id",
            itemId=eventId,
            completedAt=completedAt,
        )

    def failCalendarReminder(
        self,
        accountKey: str,
        eventId: str,
        errorType: str,
        failedAt: datetime | None = None,
    ) -> None:
        """Return a reminder to the backlog with bounded exponential delay."""
        self._failJob(
            tableName="calendar_reminders",
            accountKey=accountKey,
            itemColumn="event_id",
            itemId=eventId,
            errorType=errorType,
            failedAt=failedAt,
        )

    def queueEmailTriage(self, accountKey: str, messageId: str) -> None:
        """Queue a newly indexed message exactly once for background classification."""
        with self.database.connectDatabase() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO email_triage_jobs (
                       account_key, message_id, status, next_attempt_at
                   ) VALUES (?, ?, 'PENDING', ?)""",
                (accountKey, messageId, datetime.now(UTC).isoformat()),
            )

    def claimEmailTriage(self, now: datetime | None = None) -> dict[str, object] | None:
        """Atomically claim the oldest due email triage job with bounded content."""
        currentTime = now or datetime.now(UTC)
        if currentTime.tzinfo is None:
            raise ValueError("Triage time must include a timezone")
        with self.database.connectDatabase() as connection:
            connection.execute("BEGIN IMMEDIATE")
            triageRow = connection.execute(
                """SELECT j.account_key, j.message_id, m.sender, m.subject,
                          m.snippet, m.body_text, m.label_ids_json, m.internal_date
                   FROM email_triage_jobs j
                   JOIN email_messages m
                     ON m.account_key = j.account_key AND m.message_id = j.message_id
                   WHERE j.status = 'PENDING' AND julianday(j.next_attempt_at) <= julianday(?)
                   ORDER BY CAST(m.internal_date AS INTEGER), j.account_key, j.message_id LIMIT 1""",
                (currentTime.isoformat(),),
            ).fetchone()
            if triageRow is None:
                return None
            connection.execute(
                "UPDATE email_triage_jobs SET status = 'PROCESSING' WHERE account_key = ? AND message_id = ?",
                (triageRow[0], triageRow[1]),
            )
        return {
            "accountKey": str(triageRow[0]),
            "messageId": str(triageRow[1]),
            "sender": str(triageRow[2]),
            "subject": str(triageRow[3]),
            "snippet": str(triageRow[4]),
            "bodyText": str(triageRow[5])[:12_000],
            "labelIds": json.loads(str(triageRow[6])),
            "internalDate": str(triageRow[7]),
        }

    def completeEmailTriage(
        self,
        accountKey: str,
        messageId: str,
        classification: dict[str, object],
        completedAt: datetime | None = None,
    ) -> None:
        """Persist the bounded classification and close one processing triage job."""
        completionTime = completedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            updateResult = connection.execute(
                """UPDATE email_triage_jobs
                   SET status = 'COMPLETE', completed_at = ?, classification_json = ?
                   WHERE account_key = ? AND message_id = ? AND status = 'PROCESSING'""",
                (
                    completionTime.isoformat(),
                    json.dumps(classification, sort_keys=True),
                    accountKey,
                    messageId,
                ),
            )
            if updateResult.rowcount != 1:
                raise LookupError("Processing email triage job was not found")

    def failEmailTriage(
        self,
        accountKey: str,
        messageId: str,
        errorType: str,
        failedAt: datetime | None = None,
    ) -> None:
        """Return a triage failure to the backlog without changing Gmail state."""
        self._failJob(
            tableName="email_triage_jobs",
            accountKey=accountKey,
            itemColumn="message_id",
            itemId=messageId,
            errorType=errorType,
            failedAt=failedAt,
        )

    def recoverInterruptedJobs(self) -> None:
        """Return jobs abandoned by a stopped dispatcher to their queues."""
        with self.database.connectDatabase() as connection:
            connection.execute(
                "UPDATE calendar_reminders SET status = 'PENDING' WHERE status = 'PROCESSING'"
            )
            connection.execute(
                "UPDATE email_triage_jobs SET status = 'PENDING' WHERE status = 'PROCESSING'"
            )

    def _completeJob(
        self,
        tableName: str,
        accountKey: str,
        itemColumn: str,
        itemId: str,
        completedAt: datetime | None,
    ) -> None:
        """Complete one claimed job using only internal constant table identifiers."""
        completionTime = completedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            updateResult = connection.execute(
                f"UPDATE {tableName} SET status = 'COMPLETE', completed_at = ? "
                f"WHERE account_key = ? AND {itemColumn} = ? AND status = 'PROCESSING'",
                (completionTime.isoformat(), accountKey, itemId),
            )
            if updateResult.rowcount != 1:
                raise LookupError("Processing Google job was not found")

    def _failJob(
        self,
        tableName: str,
        accountKey: str,
        itemColumn: str,
        itemId: str,
        errorType: str,
        failedAt: datetime | None,
    ) -> None:
        """Apply the shared bounded retry policy to one processing Google job."""
        failureTime = failedAt or datetime.now(UTC)
        with self.database.connectDatabase() as connection:
            attemptsRow = connection.execute(
                f"SELECT attempts FROM {tableName} WHERE account_key = ? "
                f"AND {itemColumn} = ? AND status = 'PROCESSING'",
                (accountKey, itemId),
            ).fetchone()
            if attemptsRow is None:
                raise LookupError("Processing Google job was not found")
            attempts = int(attemptsRow[0]) + 1
            retryAt = failureTime + timedelta(minutes=min(2**attempts, 60))
            connection.execute(
                f"UPDATE {tableName} SET status = 'PENDING', attempts = ?, "
                f"next_attempt_at = ?, error_type = ? WHERE account_key = ? AND {itemColumn} = ?",
                (attempts, retryAt.isoformat(), errorType[:200], accountKey, itemId),
            )
