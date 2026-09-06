"""Build Sage Core from private runtime configuration for container deployment."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from sage_core.app import createApp


def createConfiguredApp() -> FastAPI:
    """Create Core from required private environment variables and a managed data root."""
    dataRoot = _getRequiredEnvironmentPath("SAGE_DATA_ROOT")
    return createApp(
        approvalToken=_getRequiredEnvironmentValue("SAGE_APPROVAL_TOKEN"),
        dataRoot=dataRoot,
        databasePath=dataRoot / "database" / "sage.db",
        importRoots={
            "downloads": _getRequiredEnvironmentPath("SAGE_DOWNLOADS_IMPORT_ROOT"),
        },
        operatorToken=_getRequiredEnvironmentValue("SAGE_OPERATOR_TOKEN"),
        proposalToken=_getRequiredEnvironmentValue("SAGE_PROPOSAL_TOKEN"),
        telegramAllowedUserId=_getRequiredEnvironmentInteger("SAGE_TELEGRAM_ALLOWED_USER_ID"),
        telegramChatId=_getRequiredEnvironmentInteger("SAGE_TELEGRAM_CHAT_ID"),
        telegramIngressToken=_getRequiredEnvironmentValue("SAGE_TELEGRAM_INGRESS_TOKEN"),
        telegramTopicIds={
            "MAIN": _getRequiredEnvironmentInteger("SAGE_TELEGRAM_MAIN_TOPIC_ID"),
            "REPORTS": _getRequiredEnvironmentInteger("SAGE_TELEGRAM_REPORTS_TOPIC_ID"),
            "NOTIFICATIONS": _getRequiredEnvironmentInteger(
                "SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID"
            ),
        },
    )


def _getRequiredEnvironmentPath(name: str) -> Path:
    """Read a non-empty private path variable without silently choosing a host location."""
    return Path(_getRequiredEnvironmentValue(name)).expanduser()


def _getRequiredEnvironmentValue(name: str) -> str:
    """Read one required private setting while avoiding a misleading insecure default."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _getRequiredEnvironmentInteger(name: str) -> int:
    """Read one required integer setting and fail clearly instead of silently coercing it."""
    value = _getRequiredEnvironmentValue(name)
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
