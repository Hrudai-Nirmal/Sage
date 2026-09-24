"""Define model-visible Sage capabilities and validate every selected argument."""

from __future__ import annotations

import json
from datetime import datetime
import re

from sage_core.context_state import CONTEXT_CATEGORIES, CONTEXT_KEY_PATTERN


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
    workItemKindSchema = {
        "type": "string",
        "enum": ["TASK", "CASE", "SCHEDULE"],
    }
    evidenceSchema = {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000,
        "description": "An exact quote from the current user message requesting this change.",
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "respond",
                "description": (
                    "Reply conversationally when no configured capability should run. "
                    "Use this for questions, discussion, clarification, and ordinary chat."
                ),
                "parameters": _objectSchema(
                    {"text": {"type": "string", "minLength": 1, "maxLength": 10000}},
                    ["text"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "research_web",
                "description": (
                    "Search current public web sources when the user asks for online research, "
                    "current information, verification, or source-backed recommendations."
                ),
                "parameters": _objectSchema(
                    {"query": {"type": "string", "minLength": 1, "maxLength": 2000}},
                    ["query"],
                ),
            },
        },
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
                "name": "search_context",
                "description": (
                    "Search only the user's confirmed personal context registry. "
                    "Never treat an unconfirmed conversation inference as stored context."
                ),
                "parameters": _objectSchema(
                    {"query": {"type": "string", "maxLength": 2000}}, ["query"]
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember_context",
                "description": (
                    "Record one fact only when the user explicitly asks Sage to remember, save, "
                    "store, or note it, or gives an explicit standing instruction such as "
                    "'always' or 'from now on'. Sensitive categories always create an approval card."
                ),
                "parameters": _objectSchema(
                    {
                        "category": {
                            "type": "string",
                            "enum": sorted(CONTEXT_CATEGORIES),
                        },
                        "recordKey": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                            "pattern": r"^[a-z0-9][a-z0-9._-]*$",
                        },
                        "value": {"type": "string", "minLength": 1, "maxLength": 10000},
                        "evidenceText": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "description": "An exact quote from the current user message proving write intent.",
                        },
                    },
                    ["category", "recordKey", "value", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember_email_watch",
                "description": (
                    "Save one explicit rule to notify the user when a future incoming Gmail "
                    "message matches every required term. Use short distinctive terms taken "
                    "from the user's request; do not add inferred brands, products, or events."
                ),
                "parameters": _objectSchema(
                    {
                        "recordKey": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                            "pattern": r"^[a-z0-9][a-z0-9._-]*$",
                        },
                        "label": {"type": "string", "minLength": 1, "maxLength": 500},
                        "requiredTerms": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1, "maxLength": 100},
                            "minItems": 1,
                            "maxItems": 8,
                        },
                        "evidenceText": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "description": "An exact quote from the current user message requesting this watch.",
                        },
                    },
                    ["recordKey", "label", "requiredTerms", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "forget_context",
                "description": (
                    "Propose forgetting one exact confirmed context record after the user "
                    "explicitly asks. Redaction always requires independent approval."
                ),
                "parameters": _objectSchema(
                    {"recordId": {"type": "string", "minLength": 1, "maxLength": 100}},
                    ["recordId"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_case",
                "description": (
                    "Propose a durable case only when the user explicitly asks to create, open, "
                    "start, or track something as a case. This produces an approval card and does "
                    "not create the case until the user independently approves it."
                ),
                "parameters": _objectSchema(
                    {
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "objective": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 10_000,
                        },
                        "evidenceText": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "description": "An exact quote from the current user message requesting a case.",
                        },
                    },
                    ["title", "objective", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_task",
                "description": (
                    "Propose a task when the user explicitly asks Sage to create, add, remember, "
                    "or track an actionable item. This creates only an approval card."
                ),
                "parameters": _objectSchema(
                    {
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "description": {"type": ["string", "null"], "maxLength": 10000},
                        "priority": {
                            "type": "string",
                            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                        },
                        "dueAt": {"type": ["string", "null"], "maxLength": 100},
                        "recurrence": {"type": ["string", "null"], "maxLength": 1000},
                        "evidenceText": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "description": "An exact quote from the current user message requesting the task.",
                        },
                    },
                    ["title", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_schedule",
                "description": (
                    "Propose a future or recurring report or notification only when the user "
                    "supplies an exact timezone-aware first run. This creates only an approval card."
                ),
                "parameters": _objectSchema(
                    {
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "prompt": {"type": "string", "minLength": 1, "maxLength": 10000},
                        "kind": {"type": "string", "enum": ["REPORT", "NOTIFICATION"]},
                        "dueAt": {"type": "string", "minLength": 1, "maxLength": 100},
                        "recurrence": {
                            "anyOf": [
                                {"type": "string", "enum": ["DAILY", "WEEKLY"]},
                                {"type": "null"},
                            ]
                        },
                        "evidenceText": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "description": "An exact quote from the current user message requesting the schedule.",
                        },
                    },
                    ["title", "prompt", "kind", "dueAt", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_work_items",
                "description": (
                    "Search non-archived tasks, cases, or schedules and retrieve their exact IDs "
                    "before editing, adding details, or requesting archival."
                ),
                "parameters": _objectSchema(
                    {
                        "workItemKind": workItemKindSchema,
                        "query": {"type": "string", "maxLength": 2000},
                    },
                    ["workItemKind", "query"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_case_details",
                "description": (
                    "Retrieve one exact case with its notes and milestone IDs after resolving "
                    "the case ID with search_work_items."
                ),
                "parameters": _objectSchema(
                    {
                        "caseId": {"type": "string", "minLength": 1, "maxLength": 100},
                    },
                    ["caseId"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_work_item",
                "description": (
                    "Apply an explicitly requested reversible edit to one exact task, case, or "
                    "schedule. Never use this to archive an item."
                ),
                "parameters": _objectSchema(
                    {
                        "workItemKind": workItemKindSchema,
                        "workItemId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "description": {"type": ["string", "null"], "maxLength": 10000},
                        "objective": {"type": "string", "minLength": 1, "maxLength": 10000},
                        "priority": {
                            "type": "string",
                            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                        },
                        "dueAt": {"type": ["string", "null"], "maxLength": 100},
                        "recurrence": {
                            "anyOf": [
                                {"type": "string", "maxLength": 1000},
                                {"type": "null"},
                            ]
                        },
                        "prompt": {"type": "string", "minLength": 1, "maxLength": 10000},
                        "scheduleKind": {
                            "type": "string",
                            "enum": ["REPORT", "NOTIFICATION"],
                        },
                        "nextRunAt": {"type": "string", "maxLength": 100},
                        "status": {
                            "type": "string",
                            "enum": ["OPEN", "COMPLETED", "ACTIVE", "CLOSED", "PAUSED"],
                        },
                        "evidenceText": evidenceSchema,
                    },
                    ["workItemKind", "workItemId", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_case_note",
                "description": "Append an explicitly requested note to one exact existing case.",
                "parameters": _objectSchema(
                    {
                        "caseId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "text": {"type": "string", "minLength": 1, "maxLength": 10000},
                        "evidenceText": evidenceSchema,
                    },
                    ["caseId", "text", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_case_milestone",
                "description": "Add an explicitly requested reversible milestone to one exact case.",
                "parameters": _objectSchema(
                    {
                        "caseId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "dueAt": {"type": ["string", "null"], "maxLength": 100},
                        "evidenceText": evidenceSchema,
                    },
                    ["caseId", "title", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_case_milestone",
                "description": "Edit or complete one exact milestone under one exact case.",
                "parameters": _objectSchema(
                    {
                        "caseId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "milestoneId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "dueAt": {"type": ["string", "null"], "maxLength": 100},
                        "status": {"type": "string", "enum": ["OPEN", "COMPLETED"]},
                        "evidenceText": evidenceSchema,
                    },
                    ["caseId", "milestoneId", "evidenceText"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "archive_work_item",
                "description": (
                    "Request independent approval to archive one exact task, case, or schedule. "
                    "Archival retains the row and audit history."
                ),
                "parameters": _objectSchema(
                    {
                        "workItemKind": workItemKindSchema,
                        "workItemId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "evidenceText": evidenceSchema,
                    },
                    ["workItemKind", "workItemId", "title", "evidenceText"],
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
                "name": "draft_gmail_message",
                "description": (
                    "Save a complete versioned Gmail draft without requesting approval or sending. "
                    "Use when the user asks to draft, write, or compose an email for review."
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
                "name": "revise_gmail_draft",
                "description": (
                    "Append a new immutable version of a saved Gmail draft after an explicit user "
                    "edit. Supply the complete revised message, not only changed fields."
                ),
                "parameters": _objectSchema(
                    {
                        "draftId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "expectedVersion": {"type": "integer", "minimum": 1},
                        "accountKey": accountSchema,
                        "to": {"type": "array", "items": {"type": "string", "format": "email"}, "minItems": 1, "maxItems": 20},
                        "subject": {"type": "string", "maxLength": 2000},
                        "body": {"type": "string", "minLength": 1, "maxLength": 50000},
                    },
                    ["draftId", "expectedVersion", "accountKey", "to", "subject", "body"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_gmail_approval",
                "description": (
                    "Request Telegram approval for one exact saved Gmail draft version after the "
                    "user confirms it should be sent. Supply the complete unchanged snapshot."
                ),
                "parameters": _objectSchema(
                    {
                        "draftId": {"type": "string", "minLength": 1, "maxLength": 100},
                        "draftVersion": {"type": "integer", "minimum": 1},
                        "accountKey": accountSchema,
                        "to": {"type": "array", "items": {"type": "string", "format": "email"}, "minItems": 1, "maxItems": 20},
                        "subject": {"type": "string", "maxLength": 2000},
                        "body": {"type": "string", "minLength": 1, "maxLength": 50000},
                    },
                    ["draftId", "draftVersion", "accountKey", "to", "subject", "body"],
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

    if toolName == "respond":
        _rejectUnknownKeys(arguments, {"text"})
        responseText = arguments.get("text")
        if not isinstance(responseText, str) or not responseText.strip() or len(responseText) > 10_000:
            raise ValueError("Conversation response must be between 1 and 10000 characters")
        return {"text": responseText.strip()}

    if toolName == "research_web":
        _rejectUnknownKeys(arguments, {"query"})
        researchQuery = arguments.get("query")
        if not isinstance(researchQuery, str) or not researchQuery.strip() or len(researchQuery) > 2_000:
            raise ValueError("Research query must be between 1 and 2000 characters")
        return {"query": researchQuery.strip()}

    if toolName == "search_work_items":
        _rejectUnknownKeys(arguments, {"workItemKind", "query"})
        workItemKind = _validateWorkItemKind(arguments.get("workItemKind"))
        query = arguments.get("query")
        if not isinstance(query, str) or len(query) > 2_000:
            raise ValueError("Work-item query must be a string of at most 2000 characters")
        return {"workItemKind": workItemKind, "query": query}

    if toolName == "get_case_details":
        _rejectUnknownKeys(arguments, {"caseId"})
        return {
            "caseId": _validateWorkItemIdentifier(arguments.get("caseId"), "Case")
        }

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

    if toolName == "remember_context":
        _rejectUnknownKeys(arguments, {"category", "recordKey", "value", "evidenceText"})
        category = arguments.get("category")
        recordKey = arguments.get("recordKey")
        value = arguments.get("value")
        evidenceText = arguments.get("evidenceText")
        if category not in CONTEXT_CATEGORIES:
            raise ValueError("Context category is not supported")
        if not isinstance(recordKey, str) or CONTEXT_KEY_PATTERN.fullmatch(recordKey) is None:
            raise ValueError("Context key must be a lowercase safe identifier")
        if not isinstance(value, str) or not value.strip() or len(value) > 10_000:
            raise ValueError("Context value must be between 1 and 10000 characters")
        if not isinstance(evidenceText, str) or not evidenceText.strip() or len(evidenceText) > 2_000:
            raise ValueError("Context evidence must be between 1 and 2000 characters")
        return {
            "category": str(category),
            "recordKey": recordKey,
            "value": value.strip(),
            "evidenceText": evidenceText.strip(),
        }

    if toolName == "remember_email_watch":
        _rejectUnknownKeys(arguments, {"recordKey", "label", "requiredTerms", "evidenceText"})
        recordKey = arguments.get("recordKey")
        label = arguments.get("label")
        requiredTerms = arguments.get("requiredTerms")
        evidenceText = arguments.get("evidenceText")
        if not isinstance(recordKey, str) or CONTEXT_KEY_PATTERN.fullmatch(recordKey) is None:
            raise ValueError("Email watch key must be a lowercase safe identifier")
        if not isinstance(label, str) or not label.strip() or len(label) > 500:
            raise ValueError("Email watch label must be between 1 and 500 characters")
        if (
            not isinstance(requiredTerms, list)
            or not 1 <= len(requiredTerms) <= 8
            or any(
                not isinstance(term, str) or not term.strip() or len(term) > 100
                for term in requiredTerms
            )
        ):
            raise ValueError("Email watch terms must contain between 1 and 8 short phrases")
        normalizedTerms = list(dict.fromkeys(str(term).strip() for term in requiredTerms))
        if not isinstance(evidenceText, str) or not evidenceText.strip() or len(evidenceText) > 2_000:
            raise ValueError("Email watch evidence must be between 1 and 2000 characters")
        return {
            "recordKey": recordKey,
            "label": label.strip(),
            "requiredTerms": normalizedTerms,
            "evidenceText": evidenceText.strip(),
        }

    if toolName == "forget_context":
        _rejectUnknownKeys(arguments, {"recordId"})
        recordId = arguments.get("recordId")
        if not isinstance(recordId, str) or not recordId.strip() or len(recordId) > 100:
            raise ValueError("Context record ID is invalid")
        return {"recordId": recordId.strip()}

    if toolName == "propose_case":
        _rejectUnknownKeys(arguments, {"title", "objective", "evidenceText"})
        title = arguments.get("title")
        objective = arguments.get("objective")
        evidenceText = arguments.get("evidenceText")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise ValueError("Case title must be between 1 and 500 characters")
        if (
            not isinstance(objective, str)
            or not objective.strip()
            or len(objective) > 10_000
        ):
            raise ValueError("Case objective must be between 1 and 10000 characters")
        if not isinstance(evidenceText, str) or not evidenceText.strip() or len(evidenceText) > 2_000:
            raise ValueError("Case evidence must be between 1 and 2000 characters")
        return {
            "title": title.strip(),
            "objective": objective.strip(),
            "evidenceText": evidenceText.strip(),
        }

    if toolName == "propose_task":
        _rejectUnknownKeys(
            arguments,
            {"title", "description", "priority", "dueAt", "recurrence", "evidenceText"},
        )
        title = _validateBoundedOptionalString(arguments.get("title"), "Task title", 500, True)
        description = _validateBoundedOptionalString(
            arguments.get("description"), "Task description", 10_000
        )
        priority = arguments.get("priority", "MEDIUM")
        if priority not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("Task priority is not supported")
        dueAt = _validateBoundedOptionalString(arguments.get("dueAt"), "Task dueAt", 100)
        if dueAt is not None:
            _validateTimezoneAwareTimestamp(dueAt, "Task dueAt")
        recurrence = _validateBoundedOptionalString(
            arguments.get("recurrence"), "Task recurrence", 1_000
        )
        evidenceText = _validateEvidenceText(arguments.get("evidenceText"), "Task")
        return {
            "title": title,
            "description": description,
            "priority": str(priority),
            "dueAt": dueAt,
            "recurrence": recurrence,
            "evidenceText": evidenceText,
        }

    if toolName == "propose_schedule":
        _rejectUnknownKeys(
            arguments,
            {"title", "prompt", "kind", "dueAt", "recurrence", "evidenceText"},
        )
        title = _validateBoundedOptionalString(arguments.get("title"), "Schedule title", 500, True)
        prompt = _validateBoundedOptionalString(
            arguments.get("prompt"), "Schedule prompt", 10_000, True
        )
        kind = arguments.get("kind")
        if kind not in {"REPORT", "NOTIFICATION"}:
            raise ValueError("Schedule kind is not supported")
        dueAt = _validateBoundedOptionalString(
            arguments.get("dueAt"), "Schedule dueAt", 100, True
        )
        _validateTimezoneAwareTimestamp(str(dueAt), "Schedule dueAt")
        recurrence = arguments.get("recurrence")
        if recurrence not in {None, "DAILY", "WEEKLY"}:
            raise ValueError("Schedule recurrence is not supported")
        evidenceText = _validateEvidenceText(arguments.get("evidenceText"), "Schedule")
        return {
            "title": title,
            "prompt": prompt,
            "kind": str(kind),
            "dueAt": dueAt,
            "recurrence": recurrence,
            "evidenceText": evidenceText,
        }

    if toolName == "update_work_item":
        commonKeys = {"workItemKind", "workItemId", "evidenceText"}
        allowedChangeKeys = {
            "TASK": {"title", "description", "priority", "dueAt", "recurrence", "status"},
            "CASE": {"title", "objective", "status"},
            "SCHEDULE": {
                "title",
                "prompt",
                "scheduleKind",
                "recurrence",
                "nextRunAt",
                "status",
            },
        }
        workItemKind = _validateWorkItemKind(arguments.get("workItemKind"))
        unsupportedKeys = set(arguments) - commonKeys - allowedChangeKeys[workItemKind]
        if unsupportedKeys:
            raise ValueError(f"{workItemKind.title()} update contains unsupported fields")
        workItemId = _validateWorkItemIdentifier(arguments.get("workItemId"), "Work-item")
        rawChanges = {
            fieldName: fieldValue
            for fieldName, fieldValue in arguments.items()
            if fieldName not in commonKeys
        }
        if not rawChanges:
            raise ValueError(f"{workItemKind.title()} update requires at least one changed field")
        changes = _validateWorkItemChanges(workItemKind, rawChanges)
        return {
            "workItemKind": workItemKind,
            "workItemId": workItemId,
            "changes": changes,
            "evidenceText": _validateEvidenceText(arguments.get("evidenceText"), "Work-item"),
        }

    if toolName == "add_case_note":
        _rejectUnknownKeys(arguments, {"caseId", "text", "evidenceText"})
        noteText = _validateBoundedOptionalString(
            arguments.get("text"), "Case note", 10_000, True
        )
        return {
            "caseId": _validateWorkItemIdentifier(arguments.get("caseId"), "Case"),
            "text": noteText,
            "evidenceText": _validateEvidenceText(arguments.get("evidenceText"), "Case note"),
        }

    if toolName == "add_case_milestone":
        _rejectUnknownKeys(arguments, {"caseId", "title", "dueAt", "evidenceText"})
        dueAt = _validateBoundedOptionalString(arguments.get("dueAt"), "Milestone dueAt", 100)
        if dueAt is not None:
            _validateTimezoneAwareTimestamp(dueAt, "Milestone dueAt")
        return {
            "caseId": _validateWorkItemIdentifier(arguments.get("caseId"), "Case"),
            "title": _validateBoundedOptionalString(
                arguments.get("title"), "Milestone title", 500, True
            ),
            "dueAt": dueAt,
            "evidenceText": _validateEvidenceText(arguments.get("evidenceText"), "Milestone"),
        }

    if toolName == "update_case_milestone":
        identityKeys = {"caseId", "milestoneId", "evidenceText"}
        _rejectUnknownKeys(arguments, identityKeys | {"title", "dueAt", "status"})
        rawChanges = {
            fieldName: fieldValue
            for fieldName, fieldValue in arguments.items()
            if fieldName not in identityKeys
        }
        if not rawChanges:
            raise ValueError("Milestone update requires at least one changed field")
        changes: dict[str, object] = {}
        if "title" in rawChanges:
            changes["title"] = _validateBoundedOptionalString(
                rawChanges["title"], "Milestone title", 500, True
            )
        if "dueAt" in rawChanges:
            dueAt = _validateBoundedOptionalString(rawChanges["dueAt"], "Milestone dueAt", 100)
            if dueAt is not None:
                _validateTimezoneAwareTimestamp(dueAt, "Milestone dueAt")
            changes["dueAt"] = dueAt
        if "status" in rawChanges:
            if rawChanges["status"] not in {"OPEN", "COMPLETED"}:
                raise ValueError("Milestone status is not supported")
            changes["status"] = rawChanges["status"]
        return {
            "caseId": _validateWorkItemIdentifier(arguments.get("caseId"), "Case"),
            "milestoneId": _validateWorkItemIdentifier(
                arguments.get("milestoneId"), "Milestone"
            ),
            "changes": changes,
            "evidenceText": _validateEvidenceText(arguments.get("evidenceText"), "Milestone"),
        }

    if toolName == "archive_work_item":
        _rejectUnknownKeys(
            arguments, {"workItemKind", "workItemId", "title", "evidenceText"}
        )
        return {
            "workItemKind": _validateWorkItemKind(arguments.get("workItemKind")),
            "workItemId": _validateWorkItemIdentifier(arguments.get("workItemId"), "Work-item"),
            "title": _validateBoundedOptionalString(
                arguments.get("title"), "Work-item title", 500, True
            ),
            "evidenceText": _validateEvidenceText(arguments.get("evidenceText"), "Archive"),
        }

    if toolName in {
        "draft_gmail_message",
        "request_gmail_approval",
        "revise_gmail_draft",
        "send_gmail_message",
    }:
        identityKeys: set[str] = set()
        if toolName == "revise_gmail_draft":
            identityKeys = {"draftId", "expectedVersion"}
        elif toolName == "request_gmail_approval":
            identityKeys = {"draftId", "draftVersion"}
        _rejectUnknownKeys(arguments, {"accountKey", "to", "subject", "body"} | identityKeys)
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
        validatedMessage: dict[str, object] = {
            "accountKey": str(arguments["accountKey"]),
            "to": recipients,
            "subject": subject.strip(),
            "body": body,
        }
        if identityKeys:
            draftId = arguments.get("draftId")
            versionKey = "expectedVersion" if toolName == "revise_gmail_draft" else "draftVersion"
            draftVersion = arguments.get(versionKey)
            if not isinstance(draftId, str) or not draftId.strip() or len(draftId) > 100:
                raise ValueError("Email draft ID is invalid")
            if not isinstance(draftVersion, int) or draftVersion < 1:
                raise ValueError("Email draft version is invalid")
            validatedMessage["draftId"] = draftId.strip()
            validatedMessage[versionKey] = draftVersion
        return validatedMessage

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


def _validateBoundedOptionalString(
    value: object, fieldLabel: str, maximumLength: int, isRequired: bool = False
) -> str | None:
    """Validate a nullable model field without silently stringifying other types."""
    if value is None and not isRequired:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximumLength:
        raise ValueError(f"{fieldLabel} is invalid")
    return value.strip()


def _validateEvidenceText(value: object, toolLabel: str) -> str:
    """Validate bounded exact-message evidence supplied by a semantic tool choice."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2_000:
        raise ValueError(f"{toolLabel} evidence must be between 1 and 2000 characters")
    return value.strip()


def _validateWorkItemKind(value: object) -> str:
    """Restrict lifecycle operations to the three persisted work-item families."""
    if value not in {"TASK", "CASE", "SCHEDULE"}:
        raise ValueError("Work-item kind is not supported")
    return str(value)


def _validateWorkItemIdentifier(value: object, fieldLabel: str) -> str:
    """Accept only bounded identifiers that are safe to embed in a Core URL path."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 100
        or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
    ):
        raise ValueError(f"{fieldLabel} ID is invalid")
    return value


def _validateWorkItemChanges(
    workItemKind: str, rawChanges: dict[str, object]
) -> dict[str, object]:
    """Validate lifecycle edits against the selected persisted entity type."""
    changes: dict[str, object] = {}
    stringFields = {
        "TASK": {"title": (500, True), "description": (10_000, False)},
        "CASE": {"title": (500, True), "objective": (10_000, True)},
        "SCHEDULE": {"title": (500, True), "prompt": (10_000, True)},
    }[workItemKind]
    for fieldName, (maximumLength, isRequired) in stringFields.items():
        if fieldName in rawChanges:
            changes[fieldName] = _validateBoundedOptionalString(
                rawChanges[fieldName],
                f"{workItemKind.title()} {fieldName}",
                maximumLength,
                isRequired,
            )
    if workItemKind == "TASK":
        if "priority" in rawChanges:
            if rawChanges["priority"] not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("Task priority is not supported")
            changes["priority"] = rawChanges["priority"]
        if "dueAt" in rawChanges:
            dueAt = _validateBoundedOptionalString(rawChanges["dueAt"], "Task dueAt", 100)
            if dueAt is not None:
                _validateTimezoneAwareTimestamp(dueAt, "Task dueAt")
            changes["dueAt"] = dueAt
        if "recurrence" in rawChanges:
            changes["recurrence"] = _validateBoundedOptionalString(
                rawChanges["recurrence"], "Task recurrence", 1_000
            )
        if "status" in rawChanges:
            if rawChanges["status"] not in {"OPEN", "COMPLETED"}:
                raise ValueError("Task status is not supported")
            changes["status"] = rawChanges["status"]
    elif workItemKind == "CASE":
        if "status" in rawChanges:
            if rawChanges["status"] not in {"ACTIVE", "CLOSED"}:
                raise ValueError("Case status is not supported")
            changes["status"] = rawChanges["status"]
    else:
        if "scheduleKind" in rawChanges:
            if rawChanges["scheduleKind"] not in {"REPORT", "NOTIFICATION"}:
                raise ValueError("Schedule kind is not supported")
            changes["kind"] = rawChanges["scheduleKind"]
        if "recurrence" in rawChanges:
            if rawChanges["recurrence"] not in {None, "DAILY", "WEEKLY"}:
                raise ValueError("Schedule recurrence is not supported")
            changes["recurrence"] = rawChanges["recurrence"]
        if "nextRunAt" in rawChanges:
            nextRunAt = _validateBoundedOptionalString(
                rawChanges["nextRunAt"], "Schedule nextRunAt", 100, True
            )
            _validateTimezoneAwareTimestamp(str(nextRunAt), "Schedule nextRunAt")
            changes["nextRunAt"] = nextRunAt
        if "status" in rawChanges:
            if rawChanges["status"] not in {"ACTIVE", "PAUSED"}:
                raise ValueError("Schedule status is not supported")
            changes["status"] = rawChanges["status"]
    return changes


def _validateTimezoneAwareTimestamp(value: str, fieldLabel: str) -> None:
    """Require an ISO timestamp with an explicit timezone offset."""
    try:
        parsedTimestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{fieldLabel} must be a valid ISO timestamp") from error
    if parsedTimestamp.tzinfo is None:
        raise ValueError(f"{fieldLabel} must include a timezone")


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
