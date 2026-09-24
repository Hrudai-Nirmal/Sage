"""Test reversible task, case, milestone, and schedule lifecycle operations."""

from datetime import UTC, datetime
import sqlite3

import pytest

from sage_core.database import SageDatabase
from sage_core.work_state import WorkStateRepository


def seedWorkItems(database: SageDatabase) -> None:
    """Insert approved fixtures without weakening production approval boundaries."""
    createdAt = datetime.now(UTC).isoformat()
    with database.connectDatabase() as connection:
        for approvalId, actionType in (
            ("approval-task", "CREATE_TASK"),
            ("approval-case", "CREATE_CASE"),
            ("approval-schedule", "CREATE_SCHEDULE"),
        ):
            connection.execute(
                """INSERT INTO approval_requests (
                       id, action_type, payload_json, status, created_at, expires_at
                   ) VALUES (?, ?, '{}', 'APPROVED', ?, ?)""",
                (approvalId, actionType, createdAt, "2099-01-01T00:00:00+00:00"),
            )
        connection.execute(
            """INSERT INTO tasks (
                   id, title, description, status, priority, due_at, recurrence,
                   created_at, approval_request_id
               ) VALUES ('task-1', 'Submit application', 'Apply to Acme', 'OPEN',
                         'HIGH', NULL, NULL, ?, 'approval-task')""",
            (createdAt,),
        )
        connection.execute(
            """INSERT INTO cases (
                   id, title, objective, status, created_at, approval_request_id
               ) VALUES ('case-1', 'Job search', 'Secure a developer role', 'ACTIVE',
                         ?, 'approval-case')""",
            (createdAt,),
        )
        connection.execute(
            """INSERT INTO schedules (
                   id, title, prompt, kind, status, recurrence, next_run_at,
                   created_at, approval_request_id
               ) VALUES ('schedule-1', 'Morning plan', 'Summarize open tasks', 'REPORT',
                         'ACTIVE', 'DAILY', '2026-10-01T09:00:00+05:30',
                         ?, 'approval-schedule')""",
            (createdAt,),
        )
        connection.execute(
            """INSERT INTO scheduled_deliveries (
                   id, schedule_id, due_at, status, next_attempt_at
               ) VALUES ('delivery-1', 'schedule-1', '2026-10-01T09:00:00+05:30',
                         'PENDING', '2026-10-01T09:00:00+05:30')"""
        )


def testSearchesAndUpdatesReversibleWorkItems(tmp_path):
    """Explicit edits and status changes retain stable IDs and audit history."""
    database = SageDatabase(tmp_path / "sage.db")
    seedWorkItems(database)
    repository = WorkStateRepository(database)

    task = repository.updateTask(
        "task-1",
        {"priority": "CRITICAL", "status": "COMPLETED"},
        "telegram-user:8961856168",
    )
    case = repository.updateCase(
        "case-1",
        {"status": "CLOSED"},
        "telegram-user:8961856168",
    )

    assert task["status"] == "COMPLETED"
    assert task["priority"] == "CRITICAL"
    assert case["status"] == "CLOSED"
    assert repository.searchWorkItems("TASK", "application")[0]["id"] == "task-1"
    assert repository.searchWorkItems("TASK", "completed tasks")[0]["id"] == "task-1"
    assert repository.searchWorkItems("CASE", "developer")[0]["id"] == "case-1"


def testAddsCaseNotesAndMilestonesAndUpdatesMilestone(tmp_path):
    """Case progress details are reversible automatic writes under an existing case."""
    database = SageDatabase(tmp_path / "sage.db")
    seedWorkItems(database)
    repository = WorkStateRepository(database)

    note = repository.addCaseNote(
        "case-1", "Applied to Acme", "telegram-user:8961856168"
    )
    milestone = repository.addCaseMilestone(
        "case-1",
        "Complete technical interview",
        "2026-10-10T10:00:00+05:30",
        "telegram-user:8961856168",
    )
    completedMilestone = repository.updateCaseMilestone(
        "case-1",
        str(milestone["id"]),
        {"status": "COMPLETED"},
        "telegram-user:8961856168",
    )

    assert note["text"] == "Applied to Acme"
    assert completedMilestone["status"] == "COMPLETED"
    assert repository.getCaseDetails("case-1")["milestones"][0]["status"] == "COMPLETED"
    assert repository.searchWorkItems("CASE", "job")[0]["milestones"][0]["id"] == milestone["id"]


def testSchedulePauseResumeAndRescheduleControlQueuedDeliveries(tmp_path):
    """A paused or rescheduled schedule cannot leak an obsolete pending delivery."""
    database = SageDatabase(tmp_path / "sage.db")
    seedWorkItems(database)
    repository = WorkStateRepository(database)

    pausedSchedule = repository.updateSchedule(
        "schedule-1", {"status": "PAUSED"}, "telegram-user:8961856168"
    )
    with database.connectDatabase() as connection:
        pausedDeliveryStatus = connection.execute(
            "SELECT status FROM scheduled_deliveries WHERE id = 'delivery-1'"
        ).fetchone()[0]

    resumedSchedule = repository.updateSchedule(
        "schedule-1", {"status": "ACTIVE"}, "telegram-user:8961856168"
    )
    rescheduled = repository.updateSchedule(
        "schedule-1",
        {"nextRunAt": "2026-10-02T09:00:00+05:30"},
        "telegram-user:8961856168",
    )
    with database.connectDatabase() as connection:
        replacedDeliveryStatus = connection.execute(
            "SELECT status FROM scheduled_deliveries WHERE id = 'delivery-1'"
        ).fetchone()[0]

    assert pausedSchedule["status"] == "PAUSED"
    assert pausedDeliveryStatus == "PAUSED"
    assert resumedSchedule["status"] == "ACTIVE"
    assert rescheduled["nextRunAt"] == "2026-10-02T09:00:00+05:30"
    assert replacedDeliveryStatus == "CANCELLED"


def testScheduleAndDeliveryChangesRollbackTogether(tmp_path):
    """A delivery-queue failure cannot leave its owning schedule half-updated."""
    database = SageDatabase(tmp_path / "sage.db")
    seedWorkItems(database)
    repository = WorkStateRepository(database)
    with database.connectDatabase() as connection:
        connection.execute(
            """CREATE TRIGGER reject_delivery_pause BEFORE UPDATE ON scheduled_deliveries
               BEGIN SELECT RAISE(ABORT, 'delivery update failed'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="delivery update failed"):
        repository.updateSchedule(
            "schedule-1", {"status": "PAUSED"}, "telegram-user:8961856168"
        )

    with database.connectDatabase() as connection:
        assert connection.execute(
            "SELECT status FROM schedules WHERE id = 'schedule-1'"
        ).fetchone()[0] == "ACTIVE"


def testArchivesWithoutDeletingWorkHistory(tmp_path):
    """Approved archival hides active work while retaining its durable row."""
    database = SageDatabase(tmp_path / "sage.db")
    seedWorkItems(database)
    repository = WorkStateRepository(database)

    repository.archiveWorkItem("TASK", "task-1", "telegram-user:8961856168")
    repository.archiveWorkItem("CASE", "case-1", "telegram-user:8961856168")
    repository.archiveWorkItem("SCHEDULE", "schedule-1", "telegram-user:8961856168")

    assert repository.searchWorkItems("TASK", "application") == []
    with database.connectDatabase() as connection:
        assert connection.execute("SELECT status FROM tasks WHERE id = 'task-1'").fetchone()[0] == "ARCHIVED"
        assert connection.execute("SELECT status FROM cases WHERE id = 'case-1'").fetchone()[0] == "ARCHIVED"
        assert connection.execute("SELECT status FROM schedules WHERE id = 'schedule-1'").fetchone()[0] == "ARCHIVED"


def testRejectsInvalidOrEmptyLifecycleChanges(tmp_path):
    """Lifecycle writes fail closed for missing targets and unsupported transitions."""
    database = SageDatabase(tmp_path / "sage.db")
    seedWorkItems(database)
    repository = WorkStateRepository(database)

    with pytest.raises(ValueError, match="change"):
        repository.updateTask("task-1", {}, "telegram-user:8961856168")
    with pytest.raises(ValueError, match="status"):
        repository.updateCase(
            "case-1", {"status": "ARCHIVED"}, "telegram-user:8961856168"
        )
    with pytest.raises(LookupError, match="not found"):
        repository.addCaseNote(
            "missing-case", "A note", "telegram-user:8961856168"
        )
