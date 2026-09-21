"""Centralize Sage capability awareness, authority, and bounded retry policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
import sqlite3
import time
from typing import TypeVar
from urllib.error import HTTPError, URLError


ResultType = TypeVar("ResultType")


@dataclass(frozen=True)
class CapabilityPolicy:
    """Describe one configured ability independently of model-selected wording."""

    capabilityId: str
    description: str
    authority: str
    isRetrySafe: bool
    toolName: str | None = None


class CapabilityExecutionError(RuntimeError):
    """Report exhausted technical attempts without exposing private error details."""

    def __init__(self, capabilityId: str, attempts: int) -> None:
        """Capture only stable policy metadata suitable for a user-facing failure."""
        super().__init__(f"{capabilityId} is temporarily unavailable after {attempts} attempts")
        self.capabilityId = capabilityId
        self.attempts = attempts


def getCapabilityPolicies() -> dict[str, CapabilityPolicy]:
    """Return Sage's complete code-owned capability and authority catalog."""
    policyRows = [
        ("gmail.search", "Search four connected Gmail accounts", "automatic read", True, "search_gmail"),
        (
            "gmail.monitor_important",
            "Poll all four Gmail accounts every five minutes and notify on explicit security, billing, placement, or deadline signals",
            "automatic read and Telegram notification; Gmail remains unchanged",
            True,
            None,
        ),
        ("calendar.search", "Search the personal-work Calendar snapshot", "automatic read", True, "search_calendar"),
        ("drive.search", "Search all four connected Google Drives", "automatic read", True, "search_drive"),
        ("filesystem.search_downloads", "Search allowlisted Downloads filenames", "automatic read", True, "search_downloads"),
        ("documents.search", "Search Sage-managed documents", "automatic read", True, "search_documents"),
        ("context.search", "Search confirmed personal context", "automatic read", True, "search_context"),
        ("context.remember", "Create or revise one explicitly requested context record", "ordinary records are direct; sensitive categories require the user's approval button", False, "remember_context"),
        ("context.forget", "Redact one exact context record and its retained values", "requires the user's approval button", False, "forget_context"),
        ("documents.import", "Copy an explicitly named Downloads file into Sage storage", "explicit reversible write", True, "import_download_file"),
        ("gmail.draft", "Create a versioned Gmail draft", "explicit reversible write; does not require approval", True, "draft_gmail_message"),
        ("gmail.revise_draft", "Append a version to a Gmail draft", "explicit reversible write; does not require approval", True, "revise_gmail_draft"),
        ("gmail.request_send_approval", "Request approval for an exact saved Gmail draft", "explicit proposal; requires the user's approval button", True, "request_gmail_approval"),
        ("gmail.send", "Propose and send an exact Gmail message", "sending requires the user's approval button", True, "send_gmail_message"),
        ("calendar.create", "Create a complete personal-work Calendar event", "explicit write without an approval button", True, "create_calendar_event"),
        ("calendar.update", "Update an exact personal-work Calendar event", "explicit write without an approval button", True, "update_calendar_event"),
        ("calendar.delete", "Delete an exact personal-work Calendar event", "requires the user's approval button", True, "delete_calendar_event"),
        ("drive.create_folder", "Create a Google Drive folder", "explicit non-idempotent write without an approval button", False, "create_drive_folder"),
        ("drive.rename", "Rename an exact Google Drive item", "explicit non-idempotent write without an approval button", False, "rename_drive_file"),
        ("drive.delete", "Delete an exact Google Drive item", "requires the user's approval button", False, "delete_drive_file"),
        ("online.research", "Search and extract current public web sources", "automatic read when research intent is explicit", True, None),
        ("tasks.propose", "Propose a task", "requires the user's approval button", True, None),
        (
            "cases.propose",
            "Propose a case from an explicit natural-language request",
            "requires the user's approval button",
            True,
            "propose_case",
        ),
        ("schedules.propose", "Propose scheduled work", "requires the user's approval button", True, None),
        ("vision.analyze", "Analyze a Telegram image or first PDF page with Iris", "automatic read of an explicit attachment", True, None),
        ("runtime.mode", "Switch Sage among Normal, Eco, Sleep, and Shutdown", "explicit command; restart remains Mac-only", True, None),
    ]
    return {
        capabilityId: CapabilityPolicy(
            capabilityId=capabilityId,
            description=description,
            authority=authority,
            isRetrySafe=isRetrySafe,
            toolName=toolName,
        )
        for capabilityId, description, authority, isRetrySafe, toolName in policyRows
    }


def getCapabilityAwarenessPrompt() -> str:
    """Generate the factual capability manifest injected into every Sage model turn."""
    policies = getCapabilityPolicies()
    manifestLines = [
        "## Live capability manifest (authoritative, generated by policy code)",
        "These abilities are configured. Runtime success still requires a tool receipt.",
        "Gmail means four connected Gmail accounts; Calendar means personal-work only; Drive means four connected accounts.",
    ]
    manifestLines.extend(
        f"- {policy.capabilityId}: {policy.description}; authority: {policy.authority}."
        for policy in policies.values()
    )
    manifestLines.extend(
        [
            "Never claim that a listed capability does not exist or that you inherently cannot use it.",
            "A technical failure means the capability is temporarily unavailable, not absent.",
            "An empty read result is a successful search with no matches.",
            "If the user names more than one plausible source and the intended source is unclear, ask which source to use.",
        ]
    )
    return "\n".join(manifestLines)


def executeCapability(
    capabilityName: str,
    operation: Callable[[], ResultType],
    wait: Callable[[float], None] = time.sleep,
) -> ResultType:
    """Execute with at most three technical attempts when the operation is retry-safe."""
    policy = _getPolicyByName(capabilityName)
    maximumAttempts = 3 if policy.isRetrySafe else 1
    for attemptNumber in range(1, maximumAttempts + 1):
        try:
            return operation()
        except Exception as error:
            if not _isTechnicalFailure(error):
                raise
            if attemptNumber == maximumAttempts:
                raise CapabilityExecutionError(policy.capabilityId, attemptNumber) from error
            wait(attemptNumber)
    raise RuntimeError("Capability retry loop ended unexpectedly")


def getNamedReadTools(messageText: str) -> list[str]:
    """Return explicitly named read sources without deciding among multiple matches."""
    if not isinstance(messageText, str) or not re.search(
        r"\b(?:check|search|find|show|scan|look|read|list|fetch|retrieve|what|which|"
        r"do\s+i\s+have|did\s+i\s+get)\b",
        messageText,
        flags=re.IGNORECASE,
    ):
        return []
    sourcePatterns = [
        ("search_gmail", r"\b(?:gmail|e-?mails?|mails?|inbox)\b"),
        ("search_calendar", r"\b(?:calendar|events?|meetings?|appointments?)\b"),
        ("search_drive", r"\b(?:google\s+drive|drive)\b"),
        ("search_downloads", r"\bdownloads?\b"),
        ("search_documents", r"\b(?:managed\s+documents?|sage\s+documents?)\b"),
        ("search_context", r"\b(?:context|memor(?:y|ies)|remembered\s+facts?)\b"),
    ]
    return [
        toolName
        for toolName, sourcePattern in sourcePatterns
        if re.search(sourcePattern, messageText, flags=re.IGNORECASE)
    ]


def getCapabilityDisplayName(capabilityId: str) -> str:
    """Return a concise configured-ability label for deterministic chat failures."""
    displayNames = {
        "gmail.search": "Gmail search",
        "calendar.search": "Calendar search",
        "drive.search": "Google Drive search",
        "filesystem.search_downloads": "Downloads search",
        "documents.search": "managed-document search",
        "context.search": "personal-context search",
        "context.remember": "personal-context memory",
        "context.forget": "personal-context redaction",
        "online.research": "online research",
    }
    return displayNames.get(capabilityId, capabilityId)


def getDeniedCapabilityId(replyText: str) -> str | None:
    """Detect a model claim that a configured integration does not exist."""
    if not isinstance(replyText, str) or re.search(
        r"\b(?:cannot|can['’]?t|unable|no\s+access|do\s+not\s+have\s+access|"
        r"don['’]?t\s+have\s+access|not\s+available\s+to\s+me)\b",
        replyText,
        flags=re.IGNORECASE,
    ) is None:
        return None
    capabilityPatterns = [
        ("gmail.search", r"\b(?:gmail|e-?mails?|mails?|inbox)\b"),
        ("calendar.search", r"\bcalendar\b"),
        ("drive.search", r"\b(?:google\s+drive|drive)\b"),
        ("filesystem.search_downloads", r"\bdownloads?\b"),
        ("documents.search", r"\b(?:managed\s+documents?|sage\s+documents?)\b"),
        ("context.search", r"\b(?:context|memor(?:y|ies)|remembered\s+facts?)\b"),
        ("online.research", r"\b(?:web|online|internet)\b"),
    ]
    for capabilityId, capabilityPattern in capabilityPatterns:
        if re.search(capabilityPattern, replyText, flags=re.IGNORECASE):
            return capabilityId
    return None


def _getPolicyByName(capabilityName: str) -> CapabilityPolicy:
    """Resolve either a capability ID or its registered model tool name."""
    policies = getCapabilityPolicies()
    if capabilityName in policies:
        return policies[capabilityName]
    for policy in policies.values():
        if policy.toolName == capabilityName:
            return policy
    raise ValueError("Capability is not registered")


def _isTechnicalFailure(error: Exception) -> bool:
    """Retry transport faults and transient SQLite contention, never policy failures."""
    if isinstance(error, HTTPError):
        return error.code in {408, 425, 429} or 500 <= error.code <= 599
    if isinstance(error, (TimeoutError, ConnectionError, URLError)):
        return True
    if isinstance(error, sqlite3.OperationalError):
        normalizedMessage = str(error).casefold()
        return "locked" in normalizedMessage or "busy" in normalizedMessage
    return False
