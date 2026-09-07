"""Expose the local Sage Core HTTP API used by the operator UI and n8n."""

from __future__ import annotations

from pathlib import Path
from secrets import compare_digest
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from sage_core.approval_state import ApprovalStateRepository
from sage_core.database import SageDatabase
from sage_core.document_state import DocumentStateRepository
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


class TelegramMessagePayload(BaseModel):
    """Validate the normalized inbound Telegram message sent by n8n."""

    chatId: int
    messageId: int = Field(ge=1)
    messageThreadId: int = Field(ge=1)
    senderId: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=10_000)


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


def createApp(
    databasePath: Path,
    dataRoot: Path | None = None,
    importRoots: dict[str, Path] | None = None,
    operatorToken: str = "",
    proposalToken: str = "",
    approvalToken: str = "",
    telegramAllowedUserId: int | None = None,
    telegramChatId: int | None = None,
    telegramIngressToken: str = "",
    telegramTopicIds: dict[str, int] | None = None,
) -> FastAPI:
    """Create Sage Core with an explicit SQLite path for predictable local state."""
    if not isinstance(databasePath, Path):
        raise TypeError("databasePath must be a pathlib.Path")

    managedDataRoot = dataRoot or databasePath.parent.parent
    database = SageDatabase(databasePath)
    approvalStateRepository = ApprovalStateRepository(database)
    documentStateRepository = DocumentStateRepository(
        database=database,
        dataRoot=managedDataRoot,
        importRoots=importRoots or {},
    )
    systemStateRepository = SystemStateRepository(database)
    telegramStateRepository = TelegramStateRepository(
        database=database,
        allowedUserId=telegramAllowedUserId,
        chatId=telegramChatId,
        topicIds=telegramTopicIds,
    )
    app = FastAPI(title="Sage Core", version="0.1.0")

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
        approvalRequest: TaskApprovalRequestPayload | CaseApprovalRequestPayload,
        sageProposalToken: str = Header(alias="X-Sage-Proposal-Token"),
    ) -> dict[str, str]:
        """Create a pending proposal from the constrained agent proposal channel."""
        _validateToken(sageProposalToken, proposalToken)
        return approvalStateRepository.createProposal(
            actionType=approvalRequest.actionType,
            payload=approvalRequest.payload.model_dump(),
        )

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

    @app.get("/v1/cases")
    def listCases() -> list[dict[str, str]]:
        """List only cases materialized through the approval path."""
        return approvalStateRepository.listCases()

    @app.get("/v1/audit-events")
    def listAuditEvents() -> list[dict[str, str]]:
        """List durable audit summaries for the local operator interface."""
        return approvalStateRepository.listAuditEvents()

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
