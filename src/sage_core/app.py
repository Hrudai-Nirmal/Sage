"""Expose the local Sage Core HTTP API used by the operator UI and n8n."""

from __future__ import annotations

from pathlib import Path
from secrets import compare_digest
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from sage_core.approval_state import ApprovalStateRepository
from sage_core.database import SageDatabase
from sage_core.system_state import SystemStateRepository


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


def createApp(
    databasePath: Path,
    operatorToken: str = "",
    proposalToken: str = "",
    approvalToken: str = "",
) -> FastAPI:
    """Create Sage Core with an explicit SQLite path for predictable local state."""
    if not isinstance(databasePath, Path):
        raise TypeError("databasePath must be a pathlib.Path")

    database = SageDatabase(databasePath)
    approvalStateRepository = ApprovalStateRepository(database)
    systemStateRepository = SystemStateRepository(database)
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

    return app


def _validateToken(receivedToken: str, expectedToken: str) -> None:
    """Reject empty or mismatched channel credentials without leaking their values."""
    if not expectedToken or not compare_digest(receivedToken, expectedToken):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid service credential")
