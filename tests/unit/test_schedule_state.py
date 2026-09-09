"""Unit tests for durable scheduled deliveries and missed-run recovery."""

from datetime import UTC, datetime

from sage_core.database import SageDatabase
from sage_core.schedule_state import ScheduleStateRepository


def testClaimsMissedRunAndAdvancesDailySchedule(tmp_path):
    """A run missed during downtime remains claimable and recurrence advances from its due time."""
    database = SageDatabase(tmp_path / "sage.db")
    repository = ScheduleStateRepository(database)
    schedule = repository.createSchedule(
        approvalRequestId="approval-1",
        dueAt="2026-09-09T09:00:00+05:30",
        kind="REPORT",
        prompt="Summarize today's plan",
        recurrence="DAILY",
        title="Morning plan",
    )

    delivery = repository.claimDueDelivery(datetime(2026, 9, 10, 4, 0, tzinfo=UTC))

    assert delivery is not None
    assert delivery["scheduleId"] == schedule["id"]
    assert delivery["dueAt"] == "2026-09-09T09:00:00+05:30"
    repository.completeDelivery(delivery["id"], datetime(2026, 9, 10, 4, 1, tzinfo=UTC))
    assert repository.listSchedules()[0]["nextRunAt"] == "2026-09-10T09:00:00+05:30"


def testFailedDeliveryReturnsToBacklogWithDelay(tmp_path):
    """Transient delivery failure is retained with a bounded retry timestamp."""
    database = SageDatabase(tmp_path / "sage.db")
    repository = ScheduleStateRepository(database)
    repository.createSchedule(
        approvalRequestId="approval-2",
        dueAt="2026-09-10T09:00:00+05:30",
        kind="NOTIFICATION",
        prompt="Submit the form",
        recurrence=None,
        title="Form deadline",
    )
    now = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)
    delivery = repository.claimDueDelivery(now)

    repository.failDelivery(delivery["id"], "TimeoutError", now)

    assert repository.claimDueDelivery(now) is None
    assert repository.getDeliveryStatus(delivery["id"])["status"] == "PENDING"
    assert repository.getDeliveryStatus(delivery["id"])["attempts"] == 1
