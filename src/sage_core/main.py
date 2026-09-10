"""Build Sage Core from private runtime configuration for container deployment."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI

from sage_core.app import createApp
from sage_core.database import SageDatabase
from sage_core.online_research import OnlineResearchService


def createConfiguredApp() -> FastAPI:
    """Create Core from required private environment variables and a managed data root."""
    dataRoot = _getRequiredEnvironmentPath("SAGE_DATA_ROOT")
    databasePath = dataRoot / "database" / "sage.db"
    return createApp(
        approvalToken=_getRequiredEnvironmentValue("SAGE_APPROVAL_TOKEN"),
        dataRoot=dataRoot,
        databasePath=databasePath,
        googleAccounts=_getRequiredGoogleAccounts(),
        googleCalendarAccountKey=_getRequiredEnvironmentValue(
            "SAGE_GOOGLE_CALENDAR_ACCOUNT_KEY"
        ),
        googleIngressToken=_getRequiredEnvironmentValue("SAGE_GOOGLE_INGRESS_TOKEN"),
        importRoots={
            "downloads": _getRequiredEnvironmentPath("SAGE_DOWNLOADS_IMPORT_ROOT"),
        },
        operatorToken=_getRequiredEnvironmentValue("SAGE_OPERATOR_TOKEN"),
        proposalToken=_getRequiredEnvironmentValue("SAGE_PROPOSAL_TOKEN"),
        researchService=OnlineResearchService(
            database=SageDatabase(databasePath),
            tavilyApiKey=_getRequiredEnvironmentValue("TAVILY_API_KEY"),
        ),
        researchToken=_getRequiredEnvironmentValue("SAGE_RESEARCH_TOKEN"),
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


def _getRequiredGoogleAccounts() -> dict[str, str]:
    """Read a non-empty JSON account map and reject ambiguous runtime configuration."""
    rawAccountMap = _getRequiredEnvironmentValue("SAGE_GOOGLE_ACCOUNTS_JSON")
    try:
        parsedAccountMap = json.loads(rawAccountMap)
    except json.JSONDecodeError as error:
        raise RuntimeError("SAGE_GOOGLE_ACCOUNTS_JSON must be valid JSON") from error
    if not isinstance(parsedAccountMap, dict) or not parsedAccountMap:
        raise RuntimeError("SAGE_GOOGLE_ACCOUNTS_JSON must be a non-empty object")
    if not all(
        isinstance(accountKey, str)
        and accountKey.strip()
        and isinstance(accountEmail, str)
        and accountEmail.strip()
        for accountKey, accountEmail in parsedAccountMap.items()
    ):
        raise RuntimeError("SAGE_GOOGLE_ACCOUNTS_JSON must map non-empty strings to emails")
    return {
        accountKey.strip(): accountEmail.strip()
        for accountKey, accountEmail in parsedAccountMap.items()
    }
