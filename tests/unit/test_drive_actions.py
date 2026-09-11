"""Test approval-gated Google Drive deletion jobs."""

from datetime import UTC, datetime, timedelta

from sage_core.approval_state import ApprovalStateRepository
from sage_core.database import SageDatabase
from sage_core.drive_action_state import DriveActionRepository


def testApprovedDriveDeleteBecomesOneRetryableAction(tmp_path):
    """Confirmation queues deletion; proposal and decline never call Google."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    actionRepository = DriveActionRepository(database)
    proposal = approvalRepository.createProposal(
        "DELETE_DRIVE_FILE",
        {"accountKey": "personal-work", "fileId": "file_123", "name": "Old draft"},
    )

    assert actionRepository.claimPendingAction() is None
    approvalRepository.confirmProposal(proposal["id"], "telegram:8961856168")
    action = actionRepository.claimPendingAction()

    assert action is not None
    assert action["actionType"] == "DELETE_DRIVE_FILE"
    assert action["accountKey"] == "personal-work"
    assert action["fileId"] == "file_123"
    actionRepository.failAction(action["id"], "TimeoutError", datetime(2026, 9, 11, tzinfo=UTC))
    assert actionRepository.claimPendingAction(datetime(2026, 9, 11, tzinfo=UTC)) is None
    retriedAction = actionRepository.claimPendingAction(
        datetime(2026, 9, 11, tzinfo=UTC) + timedelta(minutes=3)
    )
    assert retriedAction is not None
    actionRepository.completeAction(retriedAction["id"])
    with database.connectDatabase() as connection:
        assert connection.execute(
            "SELECT action_type, status FROM audit_events WHERE target_id = ?",
            (retriedAction["id"],),
        ).fetchone() == ("DELETE_DRIVE_FILE", "COMPLETE")
