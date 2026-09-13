"""Define model-visible Sage capabilities and validate every selected argument."""

from __future__ import annotations

import json
from datetime import datetime
import re


ACCOUNT_KEYS = {"personal-work", "work", "personal", "college"}


def _objectSchema(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    """Build one closed JSON object schema for an OpenAI-compatible tool."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def getToolDefinitions() -> list[dict[str, object]]:
    """Return only capabilities whose executors currently exist."""
    accountSchema = {
        "type": "string",
        "enum": ["personal-work", "work", "personal", "college"],
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "search_gmail",
                "description": (
                    "Search the user's connected Gmail index across all four accounts. "
                    "Use this whenever current or personal email information is requested. "
                    "Use from:sender for sender-only matching and | between alternatives."
                ),
                "parameters": _objectSchema(
                    {"query": {"type": "string", "maxLength": 2000}}, ["query"]
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_calendar",
                "description": "Search the monitored personal-work Google Calendar snapshot.",
                "parameters": _objectSchema(
                    {"query": {"type": "string", "maxLength": 2000}}, ["query"]
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_drive",
                "description": "Search all four connected Google Drives live on demand.",
                "parameters": _objectSchema(
                    {"query": {"type": "string", "maxLength": 2000}}, ["query"]
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_downloads",
                "description": (
                    "Search filenames in the sole allowlisted host Downloads folder. This returns "
                    "metadata only and never changes a host file."
                ),
                "parameters": _objectSchema(
                    {"query": {"type": "string", "maxLength": 2000}}, ["query"]
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "Search files already copied into Sage's managed document registry.",
                "parameters": _objectSchema(
                    {"query": {"type": "string", "maxLength": 2000}}, ["query"]
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "import_download_file",
                "description": (
                    "Copy one exact relative file path from the allowlisted Downloads folder into "
                    "Sage's managed document registry. Use only when the user explicitly asks to "
                    "import or copy it. Never move, rename, or alter the host source."
                ),
                "parameters": _objectSchema(
                    {"relativePath": {"type": "string", "minLength": 1, "maxLength": 2000}},
                    ["relativePath"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_gmail_message",
                "description": (
                    "Prepare an email for independent user approval. This never sends directly; "
                    "use it only when the user explicitly asks to send an email and supplies the "
                    "account, recipients, subject, and complete body."
                ),
                "parameters": _objectSchema(
                    {
                        "accountKey": accountSchema,
                        "to": {
                            "type": "array",
                            "items": {"type": "string", "format": "email"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "subject": {"type": "string", "maxLength": 2000},
                        "body": {"type": "string", "minLength": 1, "maxLength": 50000},
                    },
                    ["accountKey", "to", "subject", "body"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_calendar_event",
                "description": (
                    "Queue a personal-work Calendar event only after the user explicitly asks to "
                    "create it and supplies exact timezone-aware start and end times."
                ),
                "parameters": _objectSchema(
                    {
                        "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "startAt": {"type": "string", "maxLength": 100},
                        "endAt": {"type": "string", "maxLength": 100},
                        "description": {"type": "string", "maxLength": 50000},
                        "location": {"type": "string", "maxLength": 2000},
                    },
                    ["summary", "startAt", "endAt"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_calendar_event",
                "description": (
                    "Queue an explicit update to one exact personal-work Calendar event."
                ),
                "parameters": _objectSchema(
                    {
                        "eventId": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "startAt": {"type": "string", "maxLength": 100},
                        "endAt": {"type": "string", "maxLength": 100},
                        "description": {"type": "string", "maxLength": 50000},
                        "location": {"type": "string", "maxLength": 2000},
                    },
                    ["eventId"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_calendar_event",
                "description": (
                    "Propose deletion of one exact personal-work Calendar event. Execution always "
                    "requires the user's independent approval button."
                ),
                "parameters": _objectSchema(
                    {
                        "eventId": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
                    },
                    ["eventId", "summary"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_drive_folder",
                "description": (
                    "Create a Google Drive folder only when the user explicitly requests it."
                ),
                "parameters": _objectSchema(
                    {
                        "accountKey": accountSchema,
                        "name": {"type": "string", "minLength": 1, "maxLength": 500},
                        "parentId": {"type": "string", "maxLength": 200},
                    },
                    ["accountKey", "name"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rename_drive_file",
                "description": (
                    "Rename one exact Google Drive item only when explicitly requested."
                ),
                "parameters": _objectSchema(
                    {
                        "accountKey": accountSchema,
                        "fileId": {"type": "string", "minLength": 1, "maxLength": 200},
                        "name": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                    ["accountKey", "fileId", "name"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_drive_file",
                "description": (
                    "Propose deletion of one exact Drive item. Execution always requires the "
                    "user's independent approval button."
                ),
                "parameters": _objectSchema(
                    {
                        "accountKey": accountSchema,
                        "fileId": {"type": "string", "minLength": 1, "maxLength": 200},
                        "name": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                    ["accountKey", "fileId", "name"],
                ),
            },
        },
    ]


def validateToolArguments(toolName: str, rawArguments: str) -> dict[str, object]:
    """Parse and validate untrusted model-selected tool arguments."""
    supportedTools = {
        tool["function"]["name"] for tool in getToolDefinitions()
    }
    if toolName not in supportedTools:
        raise ValueError("Unsupported Sage tool")
    try:
        arguments = json.loads(rawArguments)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("Tool arguments must be valid JSON") from error
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments JSON must be an object")

    if toolName.startswith("search_"):
        _rejectUnknownKeys(arguments, {"query"})
        query = arguments.get("query")
        if not isinstance(query, str) or len(query) > 2_000:
            raise ValueError("Tool query must be a string of at most 2000 characters")
        return {"query": query}

    if toolName == "import_download_file":
        _rejectUnknownKeys(arguments, {"relativePath"})
        relativePath = arguments.get("relativePath")
        if (
            not isinstance(relativePath, str)
            or not relativePath.strip()
            or len(relativePath) > 2_000
            or relativePath.startswith("/")
            or "\x00" in relativePath
            or ".." in relativePath.split("/")
        ):
            raise ValueError("Download import requires a safe relative path")
        return {"relativePath": relativePath.strip()}

    if toolName == "send_gmail_message":
        _rejectUnknownKeys(arguments, {"accountKey", "to", "subject", "body"})
        if arguments.get("accountKey") not in ACCOUNT_KEYS:
            raise ValueError("Gmail account is not configured")
        recipients = arguments.get("to")
        if not isinstance(recipients, list) or not 1 <= len(recipients) <= 20:
            raise ValueError("Gmail recipient list must contain between 1 and 20 emails")
        emailPattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        if any(not isinstance(recipient, str) or not emailPattern.fullmatch(recipient) for recipient in recipients):
            raise ValueError("Every Gmail recipient must be a valid email address")
        subject = arguments.get("subject")
        body = arguments.get("body")
        if (
            not isinstance(subject, str)
            or len(subject) > 2_000
            or "\r" in subject
            or "\n" in subject
        ):
            raise ValueError("Gmail subject must be one header-safe line of at most 2000 characters")
        if not isinstance(body, str) or not body.strip() or len(body) > 50_000:
            raise ValueError("Gmail body must be between 1 and 50000 characters")
        return {
            "accountKey": str(arguments["accountKey"]),
            "to": recipients,
            "subject": subject.strip(),
            "body": body,
        }

    if toolName in {
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
    }:
        return _validateCalendarArguments(toolName, arguments)

    requiredKeys = {"accountKey", "name"}
    if toolName != "create_drive_folder":
        requiredKeys.add("fileId")
    allowedKeys = requiredKeys | ({"parentId"} if toolName == "create_drive_folder" else set())
    _rejectUnknownKeys(arguments, allowedKeys)
    if not requiredKeys.issubset(arguments):
        raise ValueError("Drive tool is missing a required argument")
    accountKey = arguments.get("accountKey")
    if accountKey not in ACCOUNT_KEYS:
        raise ValueError("Drive account is not configured")
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 500:
        raise ValueError("Drive name must be between 1 and 500 characters")
    validatedArguments = {"accountKey": str(accountKey), "name": name.strip()}
    if toolName == "create_drive_folder":
        parentId = arguments.get("parentId", "")
        if not isinstance(parentId, str) or len(parentId) > 200:
            raise ValueError("Drive parent ID is invalid")
        validatedArguments["parentId"] = parentId
    else:
        fileId = arguments.get("fileId")
        if not isinstance(fileId, str) or not fileId or len(fileId) > 200:
            raise ValueError("Drive file ID is invalid")
        if not all(character.isalnum() or character in "_-" for character in fileId):
            raise ValueError("Drive file ID is invalid")
        validatedArguments["fileId"] = fileId
    return validatedArguments


def _rejectUnknownKeys(arguments: dict[str, object], allowedKeys: set[str]) -> None:
    """Reject extra model fields rather than silently broadening a request."""
    if set(arguments) - allowedKeys:
        raise ValueError("Tool arguments contain unsupported fields")


def _validateCalendarArguments(
    toolName: str, arguments: dict[str, object]
) -> dict[str, object]:
    """Validate exact Calendar targets without inventing event details."""
    fieldLimits = {
        "description": 50_000,
        "endAt": 100,
        "eventId": 1_000,
        "location": 2_000,
        "startAt": 100,
        "summary": 2_000,
    }
    allowedKeys = set(fieldLimits)
    _rejectUnknownKeys(arguments, allowedKeys)
    requiredKeys = {
        "create_calendar_event": {"summary", "startAt", "endAt"},
        "update_calendar_event": {"eventId"},
        "delete_calendar_event": {"eventId", "summary"},
    }[toolName]
    if not requiredKeys.issubset(arguments):
        raise ValueError("Calendar tool is missing a required argument")
    validatedArguments: dict[str, object] = {}
    for fieldName, fieldValue in arguments.items():
        if not isinstance(fieldValue, str) or len(fieldValue) > fieldLimits[fieldName]:
            raise ValueError(f"Calendar {fieldName} is invalid")
        if fieldName in requiredKeys and not fieldValue.strip():
            raise ValueError(f"Calendar {fieldName} is required")
        validatedArguments[fieldName] = fieldValue.strip()
    if toolName == "update_calendar_event" and set(arguments) == {"eventId"}:
        raise ValueError("Calendar update must contain at least one changed field")
    if "startAt" in arguments or "endAt" in arguments:
        if not {"startAt", "endAt"}.issubset(arguments):
            raise ValueError("Calendar startAt and endAt must be supplied together")
        try:
            startAt = datetime.fromisoformat(str(arguments["startAt"]))
            endAt = datetime.fromisoformat(str(arguments["endAt"]))
        except ValueError as error:
            raise ValueError("Calendar times must be valid ISO timestamps") from error
        if startAt.tzinfo is None or endAt.tzinfo is None:
            raise ValueError("Calendar times must include a timezone")
        if endAt <= startAt:
            raise ValueError("Calendar end time must be after its start time")
    return validatedArguments
