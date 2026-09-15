"""Test durable, approval-aware Gmail and Calendar action delivery."""

from datetime import UTC, datetime, timedelta

from sage_core.approval_state import ApprovalStateRepository
from sage_core.database import SageDatabase
from sage_core.email_draft_state import EmailDraftStateRepository
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
    claimTime = datetime.now(UTC) + timedelta(seconds=1)
    claimedAction = actionRepository.claimPendingAction(claimTime)

    assert secondAction == firstAction
    assert claimedAction is not None
    assert claimedAction["actionType"] == "CREATE_CALENDAR_EVENT"
    assert claimedAction["payload"] == payload
    actionRepository.failAction(
        claimedAction["id"], "TimeoutError", claimTime
    )
    assert actionRepository.claimPendingAction(
        claimTime + timedelta(minutes=1)
    ) is None
    retriedAction = actionRepository.claimPendingAction(
        claimTime + timedelta(minutes=3)
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
    draftRepository = EmailDraftStateRepository(database)
    assert draftRepository.listDrafts()[0]["status"] == "SENDING"
    actionRepository.stageGmailDraft(action["id"], "draft-123")
    stagedAction = actionRepository.claimPendingAction()
    assert stagedAction is not None
    assert stagedAction["stage"] == "SEND_DRAFT"
    assert stagedAction["remoteId"] == "draft-123"
    actionRepository.completeAction(stagedAction["id"], "message-123")
    assert draftRepository.listDrafts()[0]["status"] == "SENT"


def testGmailFailureAndQuarantineAreVisibleOnTheBoundDraft(tmp_path):
    """Draft status must expose retry failures and safety quarantine to the operator."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    actionRepository = GoogleActionRepository(database)
    draftRepository = EmailDraftStateRepository(database)
    proposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE",
        {
            "accountKey": "work",
            "to": ["recipient@example.com"],
            "subject": "Status check",
            "body": "Please confirm receipt.",
        },
    )
    approvalRepository.confirmProposal(proposal["id"], "telegram:8961856168")
    claimedAction = actionRepository.claimPendingAction()
    assert claimedAction is not None

    actionRepository.failAction(
        str(claimedAction["id"]), "TimeoutError", datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert draftRepository.listDrafts()[0]["status"] == "FAILED"

    retryAction = actionRepository.claimPendingAction(
        datetime(2026, 9, 14, tzinfo=UTC) + timedelta(minutes=3)
    )
    assert retryAction is not None
    actionRepository.failAction(
        str(retryAction["id"]), "InvalidRecipient", datetime(2026, 9, 14, tzinfo=UTC)
    )
    actionRepository.quarantinePendingAction(str(retryAction["id"]), "RECIPIENT_MISMATCH")
    assert draftRepository.listDrafts()[0]["status"] == "QUARANTINED"


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


def testMalformedPendingGoogleActionCanBeQuarantinedWithAuditEvidence(tmp_path):
    """A known-invalid action must remain durable but become ineligible for delivery."""
    database = SageDatabase(tmp_path / "sage.db")
    actionRepository = GoogleActionRepository(database)
    action = actionRepository.queueAction(
        "SEND_GMAIL_MESSAGE",
        "work",
        {
            "to": ["typo@example.com"],
            "subject": "Incorrect proposal",
            "body": "Placeholder body",
        },
        "gmail:invalid-proposal",
    )

    actionRepository.quarantinePendingAction(action["id"], "RECIPIENT_MISMATCH")

    assert actionRepository.claimPendingAction(datetime(2026, 9, 14, tzinfo=UTC)) is None
    with database.connectDatabase() as connection:
        assert connection.execute(
            "SELECT status, error_type FROM google_actions WHERE id = ?", (action["id"],)
        ).fetchone() == ("QUARANTINED", "RECIPIENT_MISMATCH")
        assert connection.execute(
            "SELECT status FROM audit_events WHERE target_id = ? ORDER BY timestamp DESC LIMIT 1",
            (action["id"],),
        ).fetchone() == ("QUARANTINED",)


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
