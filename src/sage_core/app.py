"""Expose the local Sage Core HTTP API used by the operator UI and n8n."""

from __future__ import annotations

from pathlib import Path
from secrets import compare_digest
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from sage_core.approval_state import ApprovalStateRepository
from sage_core.context_state import ContextStateRepository
from sage_core.database import SageDatabase
from sage_core.document_state import DocumentStateRepository
from sage_core.email_draft_state import EmailDraftStateRepository
from sage_core.google_state import GoogleStateRepository
from sage_core.online_research import OnlineResearchService
from sage_core.operator_state import OperatorStateRepository
from sage_core.operator_ui import getOperatorHtml
from sage_core.schedule_state import ScheduleStateRepository
from sage_core.system_state import SystemStateRepository
from sage_core.telegram_state import TelegramCallback, TelegramMessage, TelegramStateRepository


class TaskProposalPayload(BaseModel):
    """Validate the minimal personal information required to propose a task."""

    description: str | None = Field(default=None, max_length=10_000)
    dueAt: str | None = Field(default=None, max_length=100)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    recurrence: str | None = Field(default=None, max_length=1_000)
    title: str = Field(min_length=1, max_length=500)


class TaskApprovalRequestPayload(BaseModel):
    """Validate a task proposal that requires an explicit confirmation."""

    actionType: Literal["CREATE_TASK"]
    payload: TaskProposalPayload


class CaseProposalPayload(BaseModel):
    """Validate the minimum information required to propose a persistent case."""

    objective: str = Field(min_length=1, max_length=10_000)
    title: str = Field(min_length=1, max_length=500)


class CaseApprovalRequestPayload(BaseModel):
    """Validate a case proposal that requires an explicit confirmation."""

    actionType: Literal["CREATE_CASE"]
    payload: CaseProposalPayload


class ScheduleProposalPayload(BaseModel):
    """Validate an approval-gated scheduled report or notification."""

    dueAt: str = Field(min_length=1, max_length=100)
    kind: Literal["REPORT", "NOTIFICATION"]
    prompt: str = Field(min_length=1, max_length=10_000)
    recurrence: Literal["DAILY", "WEEKLY"] | None = None
    title: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validateDueAt(self) -> "ScheduleProposalPayload":
        """Require an ISO timestamp with timezone so missed-run ordering is deterministic."""
        from datetime import datetime

        dueTimestamp = datetime.fromisoformat(self.dueAt)
        if dueTimestamp.tzinfo is None:
            raise ValueError("Schedule dueAt must include a timezone")
        return self


class ScheduleApprovalRequestPayload(BaseModel):
    """Require explicit confirmation before creating recurring or future work."""

    actionType: Literal["CREATE_SCHEDULE"]
    payload: ScheduleProposalPayload


class DriveDeleteProposalPayload(BaseModel):
    """Validate one exact Drive file deletion target before approval."""

    accountKey: Literal["personal-work", "work", "personal", "college"]
    fileId: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=500)


class DriveDeleteApprovalRequestPayload(BaseModel):
    """Require independent user confirmation for every Drive deletion."""

    actionType: Literal["DELETE_DRIVE_FILE"]
    payload: DriveDeleteProposalPayload


class GmailSendProposalPayload(BaseModel):
    """Validate one complete Gmail message before presenting its approval card."""

    accountKey: Literal["personal-work", "work", "personal", "college"]
    body: str = Field(min_length=1, max_length=50_000)
    draftId: str | None = Field(default=None, min_length=1, max_length=100)
    draftVersion: int | None = Field(default=None, ge=1)
    subject: str = Field(max_length=2_000)
    to: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validateRecipients(self) -> "GmailSendProposalPayload":
        """Reject malformed recipients before content enters the durable outbox."""
        import re

        emailPattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        if any(len(recipient) > 320 or not emailPattern.fullmatch(recipient) for recipient in self.to):
            raise ValueError("Every Gmail recipient must be a valid email address")
        if "\r" in self.subject or "\n" in self.subject:
            raise ValueError("Gmail subject must be one header-safe line")
        return self


class EmailDraftCreatePayload(BaseModel):
    """Validate complete content saved as the first immutable email draft version."""

    accountKey: Literal["personal-work", "work", "personal", "college"]
    body: str = Field(min_length=1, max_length=50_000)
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    subject: str = Field(max_length=2_000)
    to: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validateMessage(self) -> "EmailDraftCreatePayload":
        """Apply the same recipient and header constraints as an approval snapshot."""
        GmailSendProposalPayload(**self.model_dump())
        return self


class EmailDraftRevisionPayload(EmailDraftCreatePayload):
    """Require optimistic concurrency before appending a revised draft version."""

    expectedVersion: int = Field(ge=1)


class EmailDraftApprovalPayload(BaseModel):
    """Deduplicate a request to approve one exact draft version."""

    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)


class GmailSendApprovalRequestPayload(BaseModel):
    """Require independent confirmation before sending any Gmail message."""

    actionType: Literal["SEND_GMAIL_MESSAGE"]
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    payload: GmailSendProposalPayload


class CalendarDeleteProposalPayload(BaseModel):
    """Validate one exact personal-work Calendar deletion target."""

    accountKey: Literal["personal-work"]
    eventId: str = Field(min_length=1, max_length=1_000)
    summary: str = Field(min_length=1, max_length=2_000)


class CalendarDeleteApprovalRequestPayload(BaseModel):
    """Require independent confirmation before Calendar deletion."""

    actionType: Literal["DELETE_CALENDAR_EVENT"]
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    payload: CalendarDeleteProposalPayload


class ApprovalConfirmationPayload(BaseModel):
    """Capture the independently verified Telegram actor who approved an action."""

    approvedBy: str = Field(min_length=1, max_length=200)


class SystemModePayload(BaseModel):
    """Restrict runtime control to the four user-approved operating modes."""

    mode: Literal["NORMAL", "ECO", "SLEEP", "SHUTDOWN"]


class DocumentImportPayload(BaseModel):
    """Specify a file relative to one Core-configured import root."""

    relativePath: str = Field(min_length=1, max_length=2_000)
    sourceRoot: str = Field(min_length=1, max_length=100)


class ContextRecordCreatePayload(BaseModel):
    """Validate one explicit ordinary context write from a constrained channel."""

    category: Literal[
        "education-work",
        "identity",
        "important-dates",
        "owned-items",
        "people",
        "preferences",
        "projects-commitments",
        "user-rules",
    ]
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    recordKey: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    sourceRef: str = Field(min_length=1, max_length=500)
    sourceType: Literal["operator-explicit", "telegram-explicit"]
    value: str = Field(min_length=1, max_length=10_000)


class ContextUpsertProposalPayload(ContextRecordCreatePayload):
    """Bind a sensitive context proposal to the version reviewed by the user."""

    expectedVersion: int = Field(ge=0)


class ContextUpsertApprovalRequestPayload(BaseModel):
    """Require independent approval for identity and other sensitive context."""

    actionType: Literal["UPSERT_CONTEXT_RECORD"]
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    payload: ContextUpsertProposalPayload


class ContextBatchUpsertProposalPayload(BaseModel):
    """Validate a bounded set of sensitive records reviewed as one operation."""

    records: list[ContextUpsertProposalPayload] = Field(min_length=1, max_length=100)


class ContextBatchUpsertApprovalRequestPayload(BaseModel):
    """Require one independent confirmation for an atomic sensitive-context batch."""

    actionType: Literal["UPSERT_CONTEXT_RECORDS"]
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    payload: ContextBatchUpsertProposalPayload


class ContextForgetProposalPayload(BaseModel):
    """Bind a forget request to one exact active context version."""

    category: str = Field(min_length=1, max_length=100)
    expectedVersion: int = Field(ge=1)
    recordId: str = Field(min_length=1, max_length=100)
    recordKey: str = Field(min_length=1, max_length=120)


class ContextForgetApprovalRequestPayload(BaseModel):
    """Require independent approval before redacting any retained context."""

    actionType: Literal["FORGET_CONTEXT_RECORD"]
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=500)
    payload: ContextForgetProposalPayload


class TelegramAttachmentPayload(BaseModel):
    """Validate bounded Telegram metadata before the host downloads an attachment."""

    fileId: str = Field(min_length=1, max_length=500)
    fileName: str = Field(min_length=1, max_length=500)
    fileSize: int | None = Field(default=None, ge=1, le=20_000_000)
    fileUniqueId: str = Field(min_length=1, max_length=500, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["PHOTO", "DOCUMENT"]
    mimeType: Literal["image/jpeg", "image/png", "image/webp", "application/pdf"]


class TelegramMessagePayload(BaseModel):
    """Validate the normalized inbound Telegram message sent by n8n."""

    chatId: int
    messageId: int = Field(ge=1)
    messageThreadId: int = Field(ge=1)
    senderId: int = Field(ge=1)
    attachment: TelegramAttachmentPayload | None = None
    text: str = Field(default="", max_length=10_000)

    @model_validator(mode="after")
    def validateMessageContent(self) -> "TelegramMessagePayload":
        """Require either conversational text or one supported attachment."""
        if not self.text.strip() and self.attachment is None:
            raise ValueError("Telegram message must contain text or an attachment")
        return self


class TelegramApprovalPayload(BaseModel):
    """Validate the Telegram account that pressed an approval callback."""

    senderId: int = Field(ge=1)


class TelegramCallbackPayload(BaseModel):
    """Validate an inline-button callback normalized by n8n."""

    callbackId: str = Field(min_length=1, max_length=200)
    chatId: int
    data: str = Field(min_length=1, max_length=64)
    messageThreadId: int = Field(ge=1)
    senderId: int = Field(ge=1)


class ResearchSearchPayload(BaseModel):
    """Bound automatic online research to a small evidence set."""

    maxResults: int = Field(default=3, ge=1, le=5)
    query: str = Field(min_length=1, max_length=2_000)


class GmailMessagePayload(BaseModel):
    """Validate one bounded Gmail message snapshot received from n8n."""

    accountEmail: str = Field(min_length=3, max_length=320)
    accountKey: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    bodyText: str = Field(max_length=50_000)
    internalDate: str = Field(min_length=1, max_length=20, pattern=r"^[0-9]+$")
    labelIds: list[str] = Field(max_length=100)
    messageId: str = Field(min_length=1, max_length=500)
    recipients: list[str] = Field(max_length=100)
    sender: str = Field(max_length=2_000)
    snippet: str = Field(max_length=10_000)
    subject: str = Field(max_length=2_000)
    threadId: str = Field(min_length=1, max_length=500)


class CalendarEventPayload(BaseModel):
    """Validate one bounded Google Calendar event snapshot received from n8n."""

    accountEmail: str = Field(min_length=3, max_length=320)
    accountKey: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    attendees: list[str] = Field(max_length=100)
    description: str = Field(max_length=50_000)
    endAt: str = Field(min_length=1, max_length=100)
    eventId: str = Field(min_length=1, max_length=1_000)
    htmlLink: str = Field(max_length=2_000)
    location: str = Field(max_length=2_000)
    startAt: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    summary: str = Field(max_length=2_000)
    updatedAt: str = Field(min_length=1, max_length=100)


class DriveFilePayload(BaseModel):
    """Validate one bounded Google Drive metadata snapshot received from n8n."""

    accountEmail: str = Field(min_length=3, max_length=320)
    accountKey: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    createdAt: str = Field(min_length=1, max_length=100)
    fileId: str = Field(min_length=1, max_length=1_000)
    mimeType: str = Field(min_length=1, max_length=500)
    modifiedAt: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=2_000)
    owners: list[str] = Field(max_length=100)
    parents: list[str] = Field(max_length=100)
    size: str = Field(max_length=100)
    webViewLink: str = Field(max_length=2_000)


def createApp(
    databasePath: Path,
    dataRoot: Path | None = None,
    googleAccounts: dict[str, str] | None = None,
    googleCalendarAccountKey: str | None = None,
    googleIngressToken: str = "",
    importRoots: dict[str, Path] | None = None,
    operatorToken: str = "",
    proposalToken: str = "",
    approvalToken: str = "",
    telegramAllowedUserId: int | None = None,
    telegramChatId: int | None = None,
    telegramIngressToken: str = "",
    telegramTopicIds: dict[str, int] | None = None,
    researchService: OnlineResearchService | None = None,
    researchToken: str = "",
) -> FastAPI:
    """Create Sage Core with an explicit SQLite path for predictable local state."""
    if not isinstance(databasePath, Path):
        raise TypeError("databasePath must be a pathlib.Path")

    managedDataRoot = dataRoot or databasePath.parent.parent
    database = SageDatabase(databasePath)
    approvalStateRepository = ApprovalStateRepository(database, managedDataRoot)
    contextStateRepository = ContextStateRepository(database, managedDataRoot)
    emailDraftStateRepository = EmailDraftStateRepository(database)
    documentStateRepository = DocumentStateRepository(
        database=database,
        dataRoot=managedDataRoot,
        importRoots=importRoots or {},
    )
    googleStateRepository = GoogleStateRepository(
        database,
        googleAccounts or {},
        calendarAccountKey=googleCalendarAccountKey,
    )
    systemStateRepository = SystemStateRepository(database)
    operatorStateRepository = OperatorStateRepository(database)
    telegramStateRepository = TelegramStateRepository(
        database=database,
        allowedUserId=telegramAllowedUserId,
        chatId=telegramChatId,
        topicIds=telegramTopicIds,
    )
    app = FastAPI(title="Sage Core", version="0.1.0")

    @app.get("/operator", response_class=HTMLResponse)
    def getOperatorDashboard() -> str:
        """Serve the local control and status surface without adding a chat channel."""
        return getOperatorHtml()

    @app.get("/v1/operator/overview")
    def getOperatorOverview() -> dict[str, object]:
        """Return the dashboard's cross-module status read model."""
        return operatorStateRepository.getOverview()

    @app.get("/v1/operator/details")
    def getOperatorDetails() -> dict[str, list[dict[str, object]]]:
        """Return recent cross-module records for the localhost dashboard."""
        return operatorStateRepository.getDetails()

    @app.post("/v1/operator/mode")
    def setOperatorMode(modeUpdate: SystemModePayload) -> dict[str, str]:
        """Persist a localhost operator mode request for host reconciliation."""
        return {"mode": systemStateRepository.setMode(modeUpdate.mode), "status": "healthy"}

    @app.get("/v1/system/status")
    def getSystemStatus() -> dict[str, str]:
        """Return the local service health and the persisted requested runtime mode."""
        return {
            "mode": systemStateRepository.getMode(),
            "status": "healthy",
        }

    @app.patch("/v1/system/mode")
    def updateSystemMode(
        modeUpdate: SystemModePayload,
        sageOperatorToken: str = Header(alias="X-Sage-Operator-Token"),
    ) -> dict[str, str]:
        """Persist a direct operator-requested mode change for service controllers."""
        _validateToken(sageOperatorToken, operatorToken)
        return {
            "mode": systemStateRepository.setMode(modeUpdate.mode),
            "status": "healthy",
        }

    @app.post("/v1/approval-requests", status_code=status.HTTP_201_CREATED)
    def createApprovalRequest(
        approvalRequest: (
            TaskApprovalRequestPayload
            | CaseApprovalRequestPayload
            | ScheduleApprovalRequestPayload
            | DriveDeleteApprovalRequestPayload
            | GmailSendApprovalRequestPayload
            | CalendarDeleteApprovalRequestPayload
            | ContextUpsertApprovalRequestPayload
            | ContextBatchUpsertApprovalRequestPayload
            | ContextForgetApprovalRequestPayload
        ),
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, str]:
        """Create a pending proposal from the constrained agent proposal channel."""
        _validateToken(sageProposalToken, proposalToken)
        try:
            return approvalStateRepository.createProposal(
                actionType=approvalRequest.actionType,
                payload=approvalRequest.payload.model_dump(),
                idempotencyKey=getattr(approvalRequest, "idempotencyKey", None),
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post("/v1/email-drafts", status_code=status.HTTP_201_CREATED)
    def createEmailDraft(
        draftPayload: EmailDraftCreatePayload,
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, object]:
        """Persist a reversible email draft without creating an approval request."""
        _validateToken(sageProposalToken, proposalToken)
        return emailDraftStateRepository.createDraft(
            draftPayload.model_dump(exclude={"idempotencyKey"}),
            draftPayload.idempotencyKey,
        )

    @app.post("/v1/email-drafts/{draftId}/versions", status_code=status.HTTP_201_CREATED)
    def reviseEmailDraft(
        draftId: str,
        draftPayload: EmailDraftRevisionPayload,
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, object]:
        """Append a version while superseding any old pending approval card."""
        _validateToken(sageProposalToken, proposalToken)
        try:
            return emailDraftStateRepository.reviseDraft(
                draftId,
                draftPayload.expectedVersion,
                draftPayload.model_dump(exclude={"expectedVersion", "idempotencyKey"}),
                draftPayload.idempotencyKey,
            )
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post(
        "/v1/email-drafts/{draftId}/versions/{draftVersion}/approval-request",
        status_code=status.HTTP_201_CREATED,
    )
    def requestEmailDraftApproval(
        draftId: str,
        draftVersion: int,
        approvalPayload: EmailDraftApprovalPayload,
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, str]:
        """Bind a new approval request to one exact current email draft version."""
        _validateToken(sageProposalToken, proposalToken)
        try:
            draft = emailDraftStateRepository.getDraft(draftId, draftVersion)
            return approvalStateRepository.createProposal(
                "SEND_GMAIL_MESSAGE",
                {
                    "accountKey": draft["accountKey"],
                    "body": draft["body"],
                    "draftId": draft["id"],
                    "draftVersion": draft["version"],
                    "subject": draft["subject"],
                    "to": draft["to"],
                },
                approvalPayload.idempotencyKey,
            )
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.get("/v1/email-drafts")
    def listEmailDrafts() -> list[dict[str, object]]:
        """List durable versions for local operator and diagnostics surfaces."""
        return emailDraftStateRepository.listDrafts()

    @app.post("/v1/approval-requests/{approvalId}/confirm")
    def confirmApprovalRequest(
        approvalId: str,
        confirmation: ApprovalConfirmationPayload,
        sageApprovalToken: str = Header(alias="X-Sage-Approval-Token"),
    ) -> dict[str, str]:
        """Confirm a pending task with a secret unavailable to agent proposal tools."""
        _validateToken(sageApprovalToken, approvalToken)
        try:
            return approvalStateRepository.confirmProposal(
                approvalId=approvalId,
                approvedBy=confirmation.approvedBy,
            )
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except TimeoutError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.get("/v1/tasks")
    def listTasks() -> list[dict[str, str | None]]:
        """List only tasks already materialized through the approval path."""
        return approvalStateRepository.listTasks()

    @app.post("/v1/context/records", status_code=status.HTTP_201_CREATED)
    def createContextRecord(
        contextRecord: ContextRecordCreatePayload,
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, object]:
        """Store one explicitly requested ordinary record; sensitive writes fail closed."""
        _validateToken(sageProposalToken, proposalToken)
        try:
            return contextStateRepository.upsertRecord(
                category=contextRecord.category,
                recordKey=contextRecord.recordKey,
                value=contextRecord.value,
                sourceType=contextRecord.sourceType,
                sourceRef=contextRecord.sourceRef,
                actor="sage-proposal-channel",
                idempotencyKey=contextRecord.idempotencyKey,
            )
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.get("/v1/context/records")
    def searchContextRecords(query: str = "", resultLimit: int = 20) -> list[dict[str, object]]:
        """Search only active confirmed context for Telegram and the operator interface."""
        try:
            return contextStateRepository.searchRecords(query, resultLimit)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.get("/v1/context/records/{recordId}")
    def getContextRecord(recordId: str) -> dict[str, object]:
        """Resolve one exact active record before a correction or forget proposal."""
        try:
            return contextStateRepository.getRecord(recordId)
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @app.get("/v1/context/records/{recordId}/revisions")
    def listContextRevisions(recordId: str) -> list[dict[str, object]]:
        """Expose a bounded local provenance trail for user review."""
        return contextStateRepository.listRevisions(recordId)

    @app.get("/v1/cases")
    def listCases() -> list[dict[str, str]]:
        """List only cases materialized through the approval path."""
        return approvalStateRepository.listCases()

    @app.get("/v1/schedules")
    def listSchedules() -> list[dict[str, str | None]]:
        """List approved schedules and their next durable run time."""
        return ScheduleStateRepository(database).listSchedules()

    @app.get("/v1/audit-events")
    def listAuditEvents() -> list[dict[str, str]]:
        """List durable audit summaries for the local operator interface."""
        return approvalStateRepository.listAuditEvents()

    @app.post("/v1/research/search")
    def searchOnline(
        researchSearch: ResearchSearchPayload,
        sageResearchToken: str = Header(alias="X-Sage-Research-Token"),
    ) -> dict[str, object]:
        """Run one authenticated read-only web search with retained citations."""
        _validateToken(sageResearchToken, researchToken)
        if researchService is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Online research is unavailable")
        try:
            return researchService.searchWeb(researchSearch.query, researchSearch.maxResults)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/v1/google/gmail/messages", status_code=status.HTTP_201_CREATED)
    def indexGmailMessage(
        gmailMessage: GmailMessagePayload,
        response: Response,
        sageGoogleIngressToken: str = Header(alias="X-Sage-Google-Ingress-Token"),
    ) -> dict[str, str]:
        """Index one authenticated Gmail snapshot without performing a remote mutation."""
        _validateToken(sageGoogleIngressToken, googleIngressToken)
        try:
            isNewMessage = googleStateRepository.indexGmailMessage(gmailMessage.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        if not isNewMessage:
            response.status_code = status.HTTP_200_OK
            return {"status": "DUPLICATE"}
        return {"status": "INDEXED"}

    @app.get("/v1/emails")
    def searchEmails(
        query: str = "",
        accountKey: str | None = None,
        resultLimit: int = 20,
    ) -> list[dict[str, object]]:
        """Search recent local Gmail snapshots for Telegram and the operator interface."""
        if len(query) > 2_000:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Email query is too long")
        try:
            return googleStateRepository.searchGmailMessages(query, accountKey, resultLimit)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/v1/google/calendar/events", status_code=status.HTTP_201_CREATED)
    def indexCalendarEvent(
        calendarEvent: CalendarEventPayload,
        response: Response,
        sageGoogleIngressToken: str = Header(alias="X-Sage-Google-Ingress-Token"),
    ) -> dict[str, str]:
        """Index one authenticated Calendar snapshot without a remote mutation."""
        _validateToken(sageGoogleIngressToken, googleIngressToken)
        try:
            eventStatus = googleStateRepository.indexCalendarEvent(calendarEvent.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        if eventStatus != "INDEXED":
            response.status_code = status.HTTP_200_OK
        return {"status": eventStatus}

    @app.get("/v1/calendar/events")
    def searchCalendarEvents(query: str = "", resultLimit: int = 20) -> list[dict[str, object]]:
        """Search local personal-work calendar snapshots."""
        if len(query) > 2_000:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Calendar query is too long")
        try:
            return googleStateRepository.searchCalendarEvents(query, resultLimit)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/v1/google/drive/files", status_code=status.HTTP_201_CREATED)
    def indexDriveFile(
        driveFile: DriveFilePayload,
        response: Response,
        sageGoogleIngressToken: str = Header(alias="X-Sage-Google-Ingress-Token"),
    ) -> dict[str, str]:
        """Index authenticated Drive metadata without reading or changing file content."""
        _validateToken(sageGoogleIngressToken, googleIngressToken)
        try:
            fileStatus = googleStateRepository.indexDriveFile(driveFile.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        if fileStatus != "INDEXED":
            response.status_code = status.HTTP_200_OK
        return {"status": fileStatus}

    @app.get("/v1/drive/files")
    def searchDriveFiles(
        query: str = "", accountKey: str | None = None, resultLimit: int = 20,
    ) -> list[dict[str, object]]:
        """Search locally indexed Drive metadata without contacting Google."""
        if len(query) > 2_000:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Drive query is too long")
        try:
            return googleStateRepository.searchDriveFiles(query, accountKey, resultLimit)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/v1/documents/imports", status_code=status.HTTP_201_CREATED)
    def importDocument(
        documentImport: DocumentImportPayload,
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, str]:
        """Copy one permitted file into Sage's managed archive without changing its source."""
        _validateToken(sageProposalToken, proposalToken)
        try:
            return documentStateRepository.importDocument(
                relativePath=documentImport.relativePath,
                sourceRoot=documentImport.sourceRoot,
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    @app.get("/v1/documents")
    def listDocuments() -> list[dict[str, str]]:
        """List documents from Sage's SQLite registry rather than the filesystem."""
        return documentStateRepository.listDocuments()

    @app.post("/v1/telegram/messages", status_code=status.HTTP_201_CREATED)
    def acceptTelegramMessage(
        messagePayload: TelegramMessagePayload,
        response: Response,
        sageTelegramIngressToken: str = Header(alias="X-Sage-Telegram-Ingress-Token"),
    ) -> dict[str, str]:
        """Accept one n8n-relayed message only after credential and forum validation."""
        _validateToken(sageTelegramIngressToken, telegramIngressToken)
        try:
            topicName, isNewMessage = telegramStateRepository.acceptMessage(
                TelegramMessage(**messagePayload.model_dump())
            )
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        if not isNewMessage:
            response.status_code = status.HTTP_200_OK
            return {"status": "DUPLICATE", "topic": topicName}
        return {"status": "ACCEPTED", "topic": topicName}

    @app.post("/v1/telegram/approval-requests/{approvalId}/confirm")
    def confirmTelegramApprovalRequest(
        approvalId: str,
        approvalPayload: TelegramApprovalPayload,
        sageApprovalToken: str = Header(alias="X-Sage-Approval-Token"),
    ) -> dict[str, str]:
        """Confirm one proposal only when the configured Telegram user pressed the callback."""
        _validateToken(sageApprovalToken, approvalToken)
        if telegramAllowedUserId is None or approvalPayload.senderId != telegramAllowedUserId:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Telegram sender is not allowlisted")
        try:
            return approvalStateRepository.confirmProposal(
                approvalId=approvalId,
                approvedBy=f"telegram:{approvalPayload.senderId}",
            )
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (TimeoutError, ValueError) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post("/v1/telegram/approval-requests/{approvalId}/decline")
    def declineTelegramApprovalRequest(
        approvalId: str,
        approvalPayload: TelegramApprovalPayload,
        sageApprovalToken: str = Header(alias="X-Sage-Approval-Token"),
    ) -> dict[str, str]:
        """Decline one proposal only when the configured Telegram user pressed the callback."""
        _validateToken(sageApprovalToken, approvalToken)
        if telegramAllowedUserId is None or approvalPayload.senderId != telegramAllowedUserId:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Telegram sender is not allowlisted")
        try:
            return approvalStateRepository.declineProposal(
                approvalId=approvalId,
                declinedBy=f"telegram:{approvalPayload.senderId}",
            )
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (TimeoutError, ValueError) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post("/v1/telegram/callbacks", status_code=status.HTTP_201_CREATED)
    def acceptTelegramCallback(
        callbackPayload: TelegramCallbackPayload,
        response: Response,
        sageTelegramIngressToken: str = Header(alias="X-Sage-Telegram-Ingress-Token"),
    ) -> dict[str, str]:
        """Accept one allowlisted approval callback for native processing."""
        _validateToken(sageTelegramIngressToken, telegramIngressToken)
        try:
            isNewCallback = telegramStateRepository.acceptCallback(
                TelegramCallback(**callbackPayload.model_dump())
            )
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        if not isNewCallback:
            response.status_code = status.HTTP_200_OK
            return {"status": "DUPLICATE"}
        return {"status": "ACCEPTED"}

    return app


def _validateToken(receivedToken: str, expectedToken: str) -> None:
    """Reject empty or mismatched channel credentials without leaking their values."""
    if not expectedToken or not compare_digest(receivedToken, expectedToken):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid service credential")
