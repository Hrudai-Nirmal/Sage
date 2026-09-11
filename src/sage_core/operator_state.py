"""Assemble the compact read model used by Sage's local operator dashboard."""

from __future__ import annotations

import json

from sage_core.database import SageDatabase
from sage_core.system_state import SystemStateRepository


class OperatorStateRepository:
    """Read cross-module counts without exposing private record payloads."""

    def __init__(self, database: SageDatabase) -> None:
        """Use Sage's authoritative local database for dashboard summaries."""
        self.database = database
        self.systemStateRepository = SystemStateRepository(database)

    def getOverview(self) -> dict[str, object]:
        """Return current mode and bounded operational counts."""
        countQueries = {
            "approvals": "SELECT COUNT(*) FROM approval_requests WHERE status = 'PENDING'",
            "auditEvents": "SELECT COUNT(*) FROM audit_events",
            "cases": "SELECT COUNT(*) FROM cases WHERE status = 'ACTIVE'",
            "calendarEvents": "SELECT COUNT(*) FROM calendar_events",
            "calendarReminders": "SELECT COUNT(*) FROM calendar_reminders WHERE status = 'PENDING'",
            "documents": "SELECT COUNT(*) FROM documents",
            "driveFiles": "SELECT COUNT(*) FROM drive_files",
            "emails": "SELECT COUNT(*) FROM email_messages",
            "emailTriage": "SELECT COUNT(*) FROM email_triage_jobs WHERE status = 'PENDING'",
            "researchRuns": "SELECT COUNT(*) FROM research_runs",
            "schedules": "SELECT COUNT(*) FROM schedules WHERE status = 'ACTIVE'",
            "tasks": "SELECT COUNT(*) FROM tasks WHERE status = 'OPEN'",
        }
        with self.database.connectDatabase() as connection:
            counts = {
                countName: int(connection.execute(countQuery).fetchone()[0])
                for countName, countQuery in countQueries.items()
            }
        return {"counts": counts, "mode": self.systemStateRepository.getMode(), "status": "healthy"}

    def getDetails(self) -> dict[str, list[dict[str, object]]]:
        """Return bounded recent records for local inspection without secret fields."""
        with self.database.connectDatabase() as connection:
            approvalRows = connection.execute(
                """SELECT id, action_type, payload_json, status, expires_at
                   FROM approval_requests ORDER BY created_at DESC LIMIT 20"""
            ).fetchall()
            taskRows = connection.execute(
                "SELECT title, status, priority, due_at FROM tasks ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            caseRows = connection.execute(
                "SELECT title, objective, status FROM cases ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            documentRows = connection.execute(
                "SELECT canonical_name, original_name, imported_at FROM documents ORDER BY imported_at DESC LIMIT 20"
            ).fetchall()
            emailRows = connection.execute(
                """SELECT account_key, sender, subject, internal_date
                   FROM email_messages ORDER BY CAST(internal_date AS INTEGER) DESC LIMIT 20"""
            ).fetchall()
            triageRows = connection.execute(
                """SELECT account_key, message_id, status, attempts FROM email_triage_jobs
                   ORDER BY next_attempt_at LIMIT 20"""
            ).fetchall()
            calendarRows = connection.execute(
                """SELECT summary, start_at, end_at, location
                   FROM calendar_events ORDER BY start_at LIMIT 20"""
            ).fetchall()
            reminderRows = connection.execute(
                """SELECT text, due_at, status FROM calendar_reminders
                   ORDER BY due_at LIMIT 20"""
            ).fetchall()
            driveRows = connection.execute(
                """SELECT account_key, name, mime_type, modified_at
                   FROM drive_files ORDER BY modified_at DESC LIMIT 20"""
            ).fetchall()
            researchRows = connection.execute(
                "SELECT query, retrieved_at FROM research_runs ORDER BY retrieved_at DESC LIMIT 20"
            ).fetchall()
            scheduleRows = connection.execute(
                "SELECT title, kind, status, recurrence, next_run_at FROM schedules ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            auditRows = connection.execute(
                """SELECT timestamp, actor, action_type, target_type, status
                   FROM audit_events ORDER BY timestamp DESC LIMIT 20"""
            ).fetchall()
        return {
            "approvals": [
                {
                    "actionType": actionType,
                    "expiresAt": expiresAt,
                    "id": approvalId,
                    "status": approvalStatus,
                    "title": str(json.loads(payloadJson).get("title", actionType)),
                }
                for approvalId, actionType, payloadJson, approvalStatus, expiresAt in approvalRows
            ],
            "auditEvents": [
                {
                    "actionType": actionType,
                    "actor": actor,
                    "status": eventStatus,
                    "targetType": targetType,
                    "timestamp": timestamp,
                }
                for timestamp, actor, actionType, targetType, eventStatus in auditRows
            ],
            "cases": [
                {"objective": objective, "status": caseStatus, "title": title}
                for title, objective, caseStatus in caseRows
            ],
            "calendarEvents": [
                {"endAt": endAt, "location": location, "startAt": startAt, "summary": summary}
                for summary, startAt, endAt, location in calendarRows
            ],
            "calendarReminders": [
                {"dueAt": dueAt, "status": reminderStatus, "text": reminderText}
                for reminderText, dueAt, reminderStatus in reminderRows
            ],
            "documents": [
                {"importedAt": importedAt, "name": canonicalName, "originalName": originalName}
                for canonicalName, originalName, importedAt in documentRows
            ],
            "driveFiles": [
                {"accountKey": accountKey, "mimeType": mimeType, "modifiedAt": modifiedAt, "name": name}
                for accountKey, name, mimeType, modifiedAt in driveRows
            ],
            "emails": [
                {"accountKey": accountKey, "internalDate": internalDate, "sender": sender, "subject": subject}
                for accountKey, sender, subject, internalDate in emailRows
            ],
            "emailTriage": [
                {"accountKey": accountKey, "attempts": attempts, "messageId": messageId, "status": triageStatus}
                for accountKey, messageId, triageStatus, attempts in triageRows
            ],
            "researchRuns": [
                {"query": query, "retrievedAt": retrievedAt}
                for query, retrievedAt in researchRows
            ],
            "schedules": [
                {
                    "kind": kind,
                    "nextRunAt": nextRunAt,
                    "recurrence": recurrence,
                    "status": scheduleStatus,
                    "title": title,
                }
                for title, kind, scheduleStatus, recurrence, nextRunAt in scheduleRows
            ],
            "tasks": [
                {"dueAt": dueAt, "priority": priority, "status": taskStatus, "title": title}
                for title, taskStatus, priority, dueAt in taskRows
            ],
        }
