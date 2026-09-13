"""Test immutable Gmail draft versions and their approval lifecycle."""

import pytest

from sage_core.approval_state import ApprovalStateRepository
from sage_core.database import SageDatabase
from sage_core.email_draft_state import EmailDraftStateRepository


def getMessage() -> dict[str, object]:
    """Return one complete Gmail snapshot suitable for a durable draft."""
    return {
        "accountKey": "work",
        "to": ["recipient@example.com"],
        "subject": "Application update",
        "body": "The requested documents are attached.",
    }


def testGmailProposalCreatesOneVersionedDraftAndBindsApproval(tmp_path):
    """Every Gmail approval must reference an immutable, inspectable draft version."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    draftRepository = EmailDraftStateRepository(database)

    proposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE", getMessage(), "telegram:42:SEND_GMAIL_MESSAGE"
    )
    duplicateProposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE", getMessage(), "telegram:42:SEND_GMAIL_MESSAGE"
    )
    drafts = draftRepository.listDrafts()

    assert duplicateProposal == proposal
    assert len(drafts) == 1
    assert drafts[0] == {
        "accountKey": "work",
        "approvalRequestId": proposal["id"],
        "body": "The requested documents are attached.",
        "id": drafts[0]["id"],
        "status": "PENDING_APPROVAL",
        "subject": "Application update",
        "to": ["recipient@example.com"],
        "version": 1,
    }

    approvalRepository.confirmProposal(proposal["id"], "telegram:8961856168")

    assert draftRepository.getDraft(drafts[0]["id"], 1)["status"] == "APPROVED"
    with database.connectDatabase() as connection:
        queuedPayload = connection.execute(
            "SELECT payload_json FROM google_actions"
        ).fetchone()[0]
    assert drafts[0]["id"] in queuedPayload


def testRevisionSupersedesOldApprovalAndRequiresTheNewVersion(tmp_path):
    """Editing a draft invalidates its old approval card and preserves both snapshots."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    draftRepository = EmailDraftStateRepository(database)
    proposal = approvalRepository.createProposal("SEND_GMAIL_MESSAGE", getMessage())
    originalDraft = draftRepository.listDrafts()[0]

    revisedDraft = draftRepository.reviseDraft(
        originalDraft["id"],
        1,
        {
            **getMessage(),
            "subject": "Corrected application update",
        },
    )

    assert revisedDraft["version"] == 2
    assert revisedDraft["status"] == "DRAFT"
    assert draftRepository.getDraft(originalDraft["id"], 1)["status"] == "SUPERSEDED"
    with pytest.raises(ValueError, match="cannot be fulfilled"):
        approvalRepository.confirmProposal(proposal["id"], "telegram:8961856168")

    newProposal = approvalRepository.createProposal(
        "SEND_GMAIL_MESSAGE",
        {
            **getMessage(),
            "subject": "Corrected application update",
            "draftId": originalDraft["id"],
            "draftVersion": 2,
        },
    )
    approvalRepository.confirmProposal(newProposal["id"], "telegram:8961856168")
    assert draftRepository.getDraft(originalDraft["id"], 2)["status"] == "APPROVED"


def testDecliningEmailApprovalCancelsOnlyItsExactDraftVersion(tmp_path):
    """A declined card closes its bound version without deleting audit history."""
    database = SageDatabase(tmp_path / "sage.db")
    approvalRepository = ApprovalStateRepository(database)
    draftRepository = EmailDraftStateRepository(database)
    proposal = approvalRepository.createProposal("SEND_GMAIL_MESSAGE", getMessage())
    draft = draftRepository.listDrafts()[0]

    approvalRepository.declineProposal(proposal["id"], "telegram:8961856168")

    assert draftRepository.getDraft(draft["id"], 1)["status"] == "CANCELLED"


def testDraftCreationAndRevisionDeduplicateDispatcherRetries(tmp_path):
    """A crash between persistence and reply cannot append duplicate draft versions."""
    database = SageDatabase(tmp_path / "sage.db")
    draftRepository = EmailDraftStateRepository(database)

    firstDraft = draftRepository.createDraft(getMessage(), "telegram:100:DRAFT")
    repeatedDraft = draftRepository.createDraft(getMessage(), "telegram:100:DRAFT")
    firstRevision = draftRepository.reviseDraft(
        firstDraft["id"],
        1,
        {**getMessage(), "body": "Updated body"},
        "telegram:101:REVISION",
    )
    repeatedRevision = draftRepository.reviseDraft(
        firstDraft["id"],
        1,
        {**getMessage(), "body": "Updated body"},
        "telegram:101:REVISION",
    )

    assert repeatedDraft == firstDraft
    assert repeatedRevision == firstRevision
    assert len(draftRepository.listDrafts()) == 2
