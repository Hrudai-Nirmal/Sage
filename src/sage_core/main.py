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
        databasePath=dataRoot / "database" / "sage.db",
        operatorToken=_getRequiredEnvironmentValue("SAGE_OPERATOR_TOKEN"),
        proposalToken=_getRequiredEnvironmentValue("SAGE_PROPOSAL_TOKEN"),
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
