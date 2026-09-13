"""Define model-visible Sage capabilities and validate every selected argument."""

from __future__ import annotations

import json


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


def validateToolArguments(toolName: str, rawArguments: str) -> dict[str, str]:
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
