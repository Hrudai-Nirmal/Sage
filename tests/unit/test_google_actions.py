"""Test durable, approval-aware Gmail and Calendar action delivery."""

from datetime import UTC, datetime, timedelta

from sage_core.approval_state import ApprovalStateRepository
from sage_core.database import SageDatabase
from sage_core.google_action_state import GoogleActionRepository


def testCalendarCreateIsIdempotentlyQueuedAndRetryable(tmp_path):
    """The same explicit Calendar request cannot create duplicate outbox entries."""
    database = SageDatabase(tmp_path / "sage.db")
    actionRepository = GoogleActionRepository(database)
    payload = {
        "eventId": "sagea1b2c3",
        "summary": "Placement interview",
        "startAt": "2026-09-15T10:00:00+05:30",
        "endAt": "2026-09-15T11:00:00+05:30",
        "description": "Technical round",
        "location": "Room 201",
    }

    firstAction = actionRepository.queueAction(
        "CREATE_CALENDAR_EVENT", "personal-work", payload, "calendar:create:sagea1b2c3"
    )
    secondAction = actionRepository.queueAction(
        "CREATE_CALENDAR_EVENT", "personal-work", payload, "calendar:create:sagea1b2c3"
    )
    with database.connectDatabase() as connection:
        assert connection.execute(
            "SELECT action_type, status FROM audit_events WHERE target_id = ?",
            (firstAction["id"],),
        ).fetchall() == [("CREATE_CALENDAR_EVENT", "PENDING")]
    claimedAction = actionRepository.claimPendingAction(
        datetime(2026, 9, 14, tzinfo=UTC)
    )

    assert secondAction == firstAction
    assert claimedAction is not None
    assert claimedAction["actionType"] == "CREATE_CALENDAR_EVENT"
    assert claimedAction["payload"] == payload
    actionRepository.failAction(
        claimedAction["id"], "TimeoutError", datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert actionRepository.claimPendingAction(
        datetime(2026, 9, 14, tzinfo=UTC) + timedelta(minutes=1)
    ) is None
    retriedAction = actionRepository.claimPendingAction(
        datetime(2026, 9, 14, tzinfo=UTC) + timedelta(minutes=3)
    )
    assert retriedAction is not None
    actionRepository.completeAction(retriedAction["id"], "google-event-1")


def testApprovedGmailSendBecomesAStagedOutboxAction(tmp_path):
    """No Gmail delivery action exists until the independent approval is confirmed."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    actionRepository = GoogleActionRepository(database)
    proposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE",
        {
            "accountKey": "work",
            "to": ["recipient@example.com"],
            "subject": "Application update",
            "body": "The requested documents are attached.",
        },
    )

    assert actionRepository.claimPendingAction() is None
    approvalRepository.confirmProposal(proposal["id"], "telegram:8961856168")
    action = actionRepository.claimPendingAction()

    assert action is not None
    assert action["actionType"] == "SEND_GMAIL_MESSAGE"
    assert action["stage"] == "CREATE_DRAFT"
    assert action["payload"]["to"] == ["recipient@example.com"]
    actionRepository.stageGmailDraft(action["id"], "draft-123")
    stagedAction = actionRepository.claimPendingAction()
    assert stagedAction is not None
    assert stagedAction["stage"] == "SEND_DRAFT"
    assert stagedAction["remoteId"] == "draft-123"


def testSensitiveProposalIsIdempotentForOneTelegramMessage(tmp_path):
    """A dispatcher retry cannot generate duplicate approval cards or outbox intents."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    payload = {
        "accountKey": "work",
        "to": ["person@example.com"],
        "subject": "Hello",
        "body": "Hi",
    }

    firstProposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE", payload, "telegram:42:SEND_GMAIL_MESSAGE"
    )
    secondProposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE", payload, "telegram:42:SEND_GMAIL_MESSAGE"
    )

    assert secondProposal == firstProposal
    with database.connectDatabase() as connection:
        assert connection.execute("SELECT COUNT(*) FROM approval_requests").fetchone()[0] == 1


def testApprovedCalendarDeleteBecomesOneOutboxAction(tmp_path):
    """Calendar deletion remains inert until a valid approval is applied."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    actionRepository = GoogleActionRepository(database)
    proposal = approvalRepository.createProposal(
        "DELETE_CALENDAR_EVENT",
        {"accountKey": "personal-work", "eventId": "event-123", "summary": "Old hold"},
    )

    approvalRepository.confirmProposal(proposal["id"], "telegram:8961856168")
    action = actionRepository.claimPendingAction()

    assert action is not None
    assert action["actionType"] == "DELETE_CALENDAR_EVENT"
    assert action["payload"]["eventId"] == "event-123"
