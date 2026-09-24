"""Own reversible work-item lifecycle changes while preserving approved creation history."""

from __future__ import annotations

from datetime import UTC, datetime
import sqlite3
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


class WorkStateRepository:
    """Manage tasks, cases, milestones, and schedules behind one bounded interface."""

    def __init__(self, database: SageDatabase) -> None:
        """Use Sage's authoritative database and shared audit repository."""
        self.database = database
        self.auditStateRepository = AuditStateRepository(database)

    def searchWorkItems(
        self, workItemKind: str, query: str = "", resultLimit: int = 20
    ) -> list[dict[str, object]]:
        """Search one exact work-item type while excluding archived records."""
        normalizedKind = workItemKind.upper()
        if normalizedKind not in {"TASK", "CASE", "SCHEDULE"}:
            raise ValueError("Work item kind is not supported")
        if not 1 <= resultLimit <= 50:
            raise ValueError("Work item result limit must be between 1 and 50")
        queryTerms = [term.casefold() for term in query.split() if term][:10]
        with self.database.connectDatabase() as connection:
            if normalizedKind == "TASK":
                searchDocument = (
                    "lower(title || ' ' || coalesce(description, '') || ' ' || status || "
                    "' ' || priority || ' task tasks')"
                )
                searchClause, searchValues = self._buildSearchClause(
                    searchDocument, queryTerms
                )
                rows = connection.execute(
                    f"""SELECT id, title, description, status, priority, due_at, recurrence
                       FROM tasks
                       WHERE status != 'ARCHIVED'
                         {searchClause}
                       ORDER BY created_at DESC LIMIT ?""",
                    (*searchValues, resultLimit),
                ).fetchall()
                return [
                    {
                        "id": taskId,
                        "title": title,
                        "description": description,
                        "status": itemStatus,
                        "priority": priority,
                        "dueAt": dueAt,
                        "recurrence": recurrence,
                    }
                    for taskId, title, description, itemStatus, priority, dueAt, recurrence
                    in rows
                ]
            if normalizedKind == "CASE":
                searchDocument = "lower(title || ' ' || objective || ' ' || status || ' case cases')"
                searchClause, searchValues = self._buildSearchClause(
                    searchDocument, queryTerms
                )
                rows = connection.execute(
                    f"""SELECT id, title, objective, status FROM cases
                       WHERE status != 'ARCHIVED'
                         {searchClause}
                       ORDER BY created_at DESC LIMIT ?""",
                    (*searchValues, resultLimit),
                ).fetchall()
                return [
                    self._getCaseDetailsInConnection(connection, str(caseId))
                    for caseId, _title, _objective, _itemStatus in rows
                ]
            searchDocument = (
                "lower(title || ' ' || prompt || ' ' || kind || ' ' || status || ' ' || "
                "coalesce(recurrence, '') || ' schedule schedules')"
            )
            searchClause, searchValues = self._buildSearchClause(
                searchDocument, queryTerms
            )
            rows = connection.execute(
                f"""SELECT id, title, prompt, kind, status, recurrence, next_run_at
                   FROM schedules
                   WHERE status != 'ARCHIVED'
                     {searchClause}
                   ORDER BY created_at DESC LIMIT ?""",
                (*searchValues, resultLimit),
            ).fetchall()
            return [
                {
                    "id": scheduleId,
                    "title": title,
                    "prompt": prompt,
                    "kind": scheduleKind,
                    "status": itemStatus,
                    "recurrence": recurrence,
                    "nextRunAt": nextRunAt,
                }
                for scheduleId, title, prompt, scheduleKind, itemStatus, recurrence, nextRunAt
                in rows
            ]

    def updateTask(
        self, taskId: str, changes: dict[str, object], actor: str
    ) -> dict[str, object]:
        """Apply one explicit reversible task edit and retain its audit receipt."""
        allowedFields = {
            "description": "description",
            "dueAt": "due_at",
            "priority": "priority",
            "recurrence": "recurrence",
            "status": "status",
            "title": "title",
        }
        normalizedChanges = self._validateChanges(changes, allowedFields)
        if "status" in normalizedChanges and normalizedChanges["status"] not in {
            "OPEN",
            "COMPLETED",
        }:
            raise ValueError("Task status is not reversible through this operation")
        if "priority" in normalizedChanges and normalizedChanges["priority"] not in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            raise ValueError("Task priority is not supported")
        return self._updateWorkItem(
            "tasks", "TASK", taskId, normalizedChanges, allowedFields, actor
        )

    def updateCase(
        self, caseId: str, changes: dict[str, object], actor: str
    ) -> dict[str, object]:
        """Apply one explicit reversible case edit or ACTIVE/CLOSED transition."""
        allowedFields = {
            "objective": "objective",
            "status": "status",
            "title": "title",
        }
        normalizedChanges = self._validateChanges(changes, allowedFields)
        if "status" in normalizedChanges and normalizedChanges["status"] not in {
            "ACTIVE",
            "CLOSED",
        }:
            raise ValueError("Case status is not reversible through this operation")
        return self._updateWorkItem(
            "cases", "CASE", caseId, normalizedChanges, allowedFields, actor
        )

    def addCaseNote(self, caseId: str, noteText: str, actor: str) -> dict[str, object]:
        """Append one immutable note to an existing non-archived case."""
        normalizedText = self._requireText(noteText, "Case note", 10_000)
        noteId = str(uuid4())
        createdAt = datetime.now(UTC).isoformat()
        with self.database.connectDatabase() as connection:
            self._requireActiveRecord(connection, "cases", caseId, "Case")
            connection.execute(
                "INSERT INTO case_notes (id, case_id, note_text, created_at) VALUES (?, ?, ?, ?)",
                (noteId, caseId, normalizedText, createdAt),
            )
            self._recordChange(connection, actor, "ADD_CASE_NOTE", "CASE", caseId)
        return {"id": noteId, "caseId": caseId, "text": normalizedText, "createdAt": createdAt}

    def addCaseMilestone(
        self, caseId: str, title: str, dueAt: str | None, actor: str
    ) -> dict[str, object]:
        """Create an OPEN milestone inside one existing case."""
        normalizedTitle = self._requireText(title, "Milestone title", 500)
        self._validateTimestamp(dueAt, "Milestone dueAt")
        milestoneId = str(uuid4())
        timestamp = datetime.now(UTC).isoformat()
        with self.database.connectDatabase() as connection:
            self._requireActiveRecord(connection, "cases", caseId, "Case")
            connection.execute(
                """INSERT INTO case_milestones (
                       id, case_id, title, status, due_at, created_at, updated_at
                   ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?)""",
                (milestoneId, caseId, normalizedTitle, dueAt, timestamp, timestamp),
            )
            self._recordChange(connection, actor, "ADD_CASE_MILESTONE", "CASE", caseId)
        return {
            "id": milestoneId,
            "caseId": caseId,
            "title": normalizedTitle,
            "status": "OPEN",
            "dueAt": dueAt,
        }

    def updateCaseMilestone(
        self,
        caseId: str,
        milestoneId: str,
        changes: dict[str, object],
        actor: str,
    ) -> dict[str, object]:
        """Edit or complete one milestone that belongs to the specified case."""
        allowedFields = {"dueAt": "due_at", "status": "status", "title": "title"}
        normalizedChanges = self._validateChanges(changes, allowedFields)
        if "status" in normalizedChanges and normalizedChanges["status"] not in {
            "OPEN",
            "COMPLETED",
        }:
            raise ValueError("Milestone status is not supported")
        if "dueAt" in normalizedChanges:
            self._validateTimestamp(normalizedChanges["dueAt"], "Milestone dueAt")
        timestamp = datetime.now(UTC).isoformat()
        assignments = [f"{allowedFields[fieldName]} = ?" for fieldName in normalizedChanges]
        values = list(normalizedChanges.values())
        with self.database.connectDatabase() as connection:
            self._requireActiveRecord(connection, "cases", caseId, "Case")
            updateResult = connection.execute(
                f"""UPDATE case_milestones SET {', '.join(assignments)}, updated_at = ?
                    WHERE id = ? AND case_id = ?""",
                (*values, timestamp, milestoneId, caseId),
            )
            if updateResult.rowcount != 1:
                raise LookupError("Case milestone was not found")
            self._recordChange(
                connection, actor, "UPDATE_CASE_MILESTONE", "CASE_MILESTONE", milestoneId
            )
            row = connection.execute(
                "SELECT title, status, due_at FROM case_milestones WHERE id = ?",
                (milestoneId,),
            ).fetchone()
        return {
            "id": milestoneId,
            "caseId": caseId,
            "title": row[0],
            "status": row[1],
            "dueAt": row[2],
        }

    def getCaseDetails(self, caseId: str) -> dict[str, object]:
        """Return one case with its bounded notes and milestones."""
        with self.database.connectDatabase() as connection:
            return self._getCaseDetailsInConnection(connection, caseId)

    def _getCaseDetailsInConnection(
        self, connection: sqlite3.Connection, caseId: str
    ) -> dict[str, object]:
        """Read one case and its child records from a consistent SQLite snapshot."""
        caseRow = connection.execute(
            "SELECT title, objective, status FROM cases WHERE id = ?",
            (caseId,),
        ).fetchone()
        if caseRow is None:
            raise LookupError("Case was not found")
        noteRows = connection.execute(
            """SELECT id, note_text, created_at FROM case_notes
               WHERE case_id = ? ORDER BY created_at DESC LIMIT 100""",
            (caseId,),
        ).fetchall()
        milestoneRows = connection.execute(
            """SELECT id, title, status, due_at FROM case_milestones
               WHERE case_id = ? ORDER BY created_at LIMIT 100""",
            (caseId,),
        ).fetchall()
        return {
            "id": caseId,
            "title": caseRow[0],
            "objective": caseRow[1],
            "status": caseRow[2],
            "notes": [
                {"id": noteId, "text": noteText, "createdAt": createdAt}
                for noteId, noteText, createdAt in noteRows
            ],
            "milestones": [
                {"id": itemId, "title": title, "status": itemStatus, "dueAt": dueAt}
                for itemId, title, itemStatus, dueAt in milestoneRows
            ],
        }

    def updateSchedule(
        self, scheduleId: str, changes: dict[str, object], actor: str
    ) -> dict[str, object]:
        """Edit, pause, or resume a schedule while reconciling queued deliveries."""
        allowedFields = {
            "kind": "kind",
            "nextRunAt": "next_run_at",
            "prompt": "prompt",
            "recurrence": "recurrence",
            "status": "status",
            "title": "title",
        }
        normalizedChanges = self._validateChanges(changes, allowedFields)
        if "status" in normalizedChanges and normalizedChanges["status"] not in {
            "ACTIVE",
            "PAUSED",
        }:
            raise ValueError("Schedule status is not reversible through this operation")
        if "kind" in normalizedChanges and normalizedChanges["kind"] not in {
            "REPORT",
            "NOTIFICATION",
        }:
            raise ValueError("Schedule kind is not supported")
        if "recurrence" in normalizedChanges and normalizedChanges["recurrence"] not in {
            None,
            "DAILY",
            "WEEKLY",
        }:
            raise ValueError("Schedule recurrence is not supported")
        if "nextRunAt" in normalizedChanges:
            self._validateTimestamp(normalizedChanges["nextRunAt"], "Schedule nextRunAt")
        with self.database.connectDatabase() as connection:
            result = self._updateWorkItem(
                "schedules",
                "SCHEDULE",
                scheduleId,
                normalizedChanges,
                allowedFields,
                actor,
                connection,
            )
            if "nextRunAt" in normalizedChanges:
                connection.execute(
                    """UPDATE scheduled_deliveries SET status = 'CANCELLED'
                       WHERE schedule_id = ? AND status IN ('PENDING', 'PAUSED')""",
                    (scheduleId,),
                )
            elif normalizedChanges.get("status") == "PAUSED":
                connection.execute(
                    """UPDATE scheduled_deliveries SET status = 'PAUSED'
                       WHERE schedule_id = ? AND status = 'PENDING'""",
                    (scheduleId,),
                )
            elif normalizedChanges.get("status") == "ACTIVE":
                connection.execute(
                    """UPDATE scheduled_deliveries SET status = 'PENDING'
                       WHERE schedule_id = ? AND status = 'PAUSED'""",
                    (scheduleId,),
                )
        return result

    def archiveWorkItem(
        self,
        workItemKind: str,
        workItemId: str,
        actor: str,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """Archive one approved target without deleting its row or audit trail."""
        kindMap = {
            "TASK": ("tasks", "TASK"),
            "CASE": ("cases", "CASE"),
            "SCHEDULE": ("schedules", "SCHEDULE"),
        }
        resolvedKind = kindMap.get(workItemKind.upper())
        if resolvedKind is None:
            raise ValueError("Work item kind is not supported")
        tableName, targetType = resolvedKind
        if connection is not None:
            self._archiveWorkItemInConnection(
                connection, tableName, targetType, workItemId, actor
            )
            return
        with self.database.connectDatabase() as ownedConnection:
            self._archiveWorkItemInConnection(
                ownedConnection, tableName, targetType, workItemId, actor
            )

    def _archiveWorkItemInConnection(
        self,
        connection: sqlite3.Connection,
        tableName: str,
        targetType: str,
        workItemId: str,
        actor: str,
    ) -> None:
        """Archive inside the caller's transaction so approval and mutation are atomic."""
        timestamp = datetime.now(UTC).isoformat()
        updateResult = connection.execute(
            f"""UPDATE {tableName} SET status = 'ARCHIVED', updated_at = ?
                WHERE id = ? AND status != 'ARCHIVED'""",
            (timestamp, workItemId),
        )
        if updateResult.rowcount != 1:
            raise LookupError(f"{targetType.title()} was not found")
        if targetType == "SCHEDULE":
            connection.execute(
                """UPDATE scheduled_deliveries SET status = 'CANCELLED'
                   WHERE schedule_id = ? AND status IN ('PENDING', 'PAUSED')""",
                (workItemId,),
            )
        self._recordChange(
            connection, actor, f"ARCHIVE_{targetType}", targetType, workItemId
        )

    def _updateWorkItem(
        self,
        tableName: str,
        targetType: str,
        workItemId: str,
        changes: dict[str, object],
        allowedFields: dict[str, str],
        actor: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        """Apply validated fields to one fixed internal table and return its public row."""
        if connection is not None:
            return self._updateWorkItemInConnection(
                connection,
                tableName,
                targetType,
                workItemId,
                changes,
                allowedFields,
                actor,
            )
        with self.database.connectDatabase() as ownedConnection:
            return self._updateWorkItemInConnection(
                ownedConnection,
                tableName,
                targetType,
                workItemId,
                changes,
                allowedFields,
                actor,
            )

    def _updateWorkItemInConnection(
        self,
        connection: sqlite3.Connection,
        tableName: str,
        targetType: str,
        workItemId: str,
        changes: dict[str, object],
        allowedFields: dict[str, str],
        actor: str,
    ) -> dict[str, object]:
        """Update and read a work item inside one caller-owned transaction."""
        assignments = [f"{allowedFields[fieldName]} = ?" for fieldName in changes]
        timestamp = datetime.now(UTC).isoformat()
        updateResult = connection.execute(
            f"""UPDATE {tableName} SET {', '.join(assignments)}, updated_at = ?
                WHERE id = ? AND status != 'ARCHIVED'""",
            (*changes.values(), timestamp, workItemId),
        )
        if updateResult.rowcount != 1:
            raise LookupError(f"{targetType.title()} was not found")
        self._recordChange(
            connection, actor, f"UPDATE_{targetType}", targetType, workItemId
        )
        return self._getWorkItemInConnection(connection, targetType, workItemId)

    def _getWorkItemInConnection(
        self, connection: sqlite3.Connection, targetType: str, workItemId: str
    ) -> dict[str, object]:
        """Return one updated work item without opening a second SQLite snapshot."""
        if targetType == "TASK":
            row = connection.execute(
                """SELECT title, description, status, priority, due_at, recurrence
                   FROM tasks WHERE id = ?""",
                (workItemId,),
            ).fetchone()
            return {
                "id": workItemId,
                "title": row[0],
                "description": row[1],
                "status": row[2],
                "priority": row[3],
                "dueAt": row[4],
                "recurrence": row[5],
            }
        if targetType == "CASE":
            row = connection.execute(
                "SELECT title, objective, status FROM cases WHERE id = ?",
                (workItemId,),
            ).fetchone()
            return {
                "id": workItemId,
                "title": row[0],
                "objective": row[1],
                "status": row[2],
            }
        row = connection.execute(
            """SELECT title, prompt, kind, status, recurrence, next_run_at
               FROM schedules WHERE id = ?""",
            (workItemId,),
        ).fetchone()
        return {
            "id": workItemId,
            "title": row[0],
            "prompt": row[1],
            "kind": row[2],
            "status": row[3],
            "recurrence": row[4],
            "nextRunAt": row[5],
        }

    def _validateChanges(
        self, changes: dict[str, object], allowedFields: dict[str, str]
    ) -> dict[str, object]:
        """Reject empty, unknown, oversized, or untyped lifecycle changes."""
        if not changes:
            raise ValueError("At least one lifecycle change is required")
        if set(changes) - set(allowedFields):
            raise ValueError("Lifecycle change contains unsupported fields")
        normalizedChanges: dict[str, object] = {}
        for fieldName, fieldValue in changes.items():
            if fieldValue is None and fieldName in {"description", "dueAt", "recurrence"}:
                normalizedChanges[fieldName] = None
                continue
            maximumLength = 10_000 if fieldName in {"description", "objective", "prompt"} else 1_000
            if not isinstance(fieldValue, str) or not fieldValue.strip() or len(fieldValue) > maximumLength:
                raise ValueError(f"Lifecycle {fieldName} is invalid")
            normalizedChanges[fieldName] = fieldValue.strip()
        return normalizedChanges

    def _buildSearchClause(
        self, searchDocument: str, queryTerms: list[str]
    ) -> tuple[str, list[str]]:
        """Require every user term while keeping values parameterized."""
        if not queryTerms:
            return "", []
        clauses = [f"AND {searchDocument} LIKE ?" for _ in queryTerms]
        return " ".join(clauses), [f"%{term}%" for term in queryTerms]

    def _requireActiveRecord(
        self,
        connection: sqlite3.Connection,
        tableName: str,
        recordId: str,
        recordLabel: str,
    ) -> None:
        """Require one existing non-archived parent before creating child state."""
        record = connection.execute(
            f"SELECT status FROM {tableName} WHERE id = ? AND status != 'ARCHIVED'",
            (recordId,),
        ).fetchone()
        if record is None:
            raise LookupError(f"{recordLabel} was not found")

    def _recordChange(
        self,
        connection: sqlite3.Connection,
        actor: str,
        actionType: str,
        targetType: str,
        targetId: str,
    ) -> None:
        """Record a completed work-item change without retaining private content."""
        self.auditStateRepository.recordEvent(
            connection=connection,
            actor=actor,
            actionType=actionType,
            targetType=targetType,
            targetId=targetId,
            eventStatus="COMPLETED",
            metadata={},
        )

    def _requireText(self, value: str, fieldLabel: str, maximumLength: int) -> str:
        """Normalize one bounded required human-authored value."""
        if not isinstance(value, str) or not value.strip() or len(value) > maximumLength:
            raise ValueError(f"{fieldLabel} is invalid")
        return value.strip()

    def _validateTimestamp(self, value: object, fieldLabel: str) -> None:
        """Validate an optional timezone-aware ISO timestamp."""
        if value is None:
            return
        if not isinstance(value, str):
            raise ValueError(f"{fieldLabel} is invalid")
        try:
            parsedTimestamp = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{fieldLabel} is invalid") from error
        if parsedTimestamp.tzinfo is None:
            raise ValueError(f"{fieldLabel} must include a timezone")
