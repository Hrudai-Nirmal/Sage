"""Test Sage's model-visible capability contracts and argument boundary."""

import pytest

from sage_core.tool_registry import getToolDefinitions, validateToolArguments


def testRegistryExposesOnlyImplementedGoogleTools():
    """The model can select real tools without inventing unavailable capabilities."""
    toolNames = {
        tool["function"]["name"] for tool in getToolDefinitions()
    }

    assert toolNames == {
        "create_calendar_event",
        "create_drive_folder",
        "delete_calendar_event",
        "delete_drive_file",
        "rename_drive_file",
        "search_calendar",
        "search_drive",
        "search_gmail",
        "send_gmail_message",
        "update_calendar_event",
    }


def testValidatesToolArgumentsAndConfiguredAccountKeys():
    """Malformed model output cannot cross the deterministic executor boundary."""
    assert validateToolArguments("search_gmail", '{"query":"from:Neon"}') == {
        "query": "from:Neon"
    }
    assert validateToolArguments(
        "create_drive_folder",
        '{"accountKey":"work","name":"Applications"}',
    ) == {"accountKey": "work", "name": "Applications", "parentId": ""}

    with pytest.raises(ValueError, match="account"):
        validateToolArguments(
            "create_drive_folder",
            '{"accountKey":"unknown","name":"Applications"}',
        )
    with pytest.raises(ValueError, match="Unsupported"):
        validateToolArguments("send_email", "{}")
    with pytest.raises(ValueError, match="JSON"):
        validateToolArguments("search_gmail", "not-json")


def testValidatesGmailSendAndCalendarMutationArguments():
    """External mutations require complete targets and timezone-aware event times."""
    assert validateToolArguments(
        "send_gmail_message",
        '{"accountKey":"work","to":["person@example.com"],"subject":"Hello","body":"Hi"}',
    ) == {
        "accountKey": "work",
        "to": ["person@example.com"],
        "subject": "Hello",
        "body": "Hi",
    }
    assert validateToolArguments(
        "create_calendar_event",
        '{"summary":"Interview","startAt":"2026-09-15T10:00:00+05:30",'
        '"endAt":"2026-09-15T11:00:00+05:30"}',
    )["summary"] == "Interview"

    with pytest.raises(ValueError, match="email"):
        validateToolArguments(
            "send_gmail_message",
            '{"accountKey":"work","to":["not-an-email"],"subject":"Hello","body":"Hi"}',
        )
    with pytest.raises(ValueError, match="subject"):
        validateToolArguments(
            "send_gmail_message",
            '{"accountKey":"work","to":["person@example.com"],'
            '"subject":"Hello\\nBcc: attacker@example.com","body":"Hi"}',
        )
    with pytest.raises(ValueError, match="timezone"):
        validateToolArguments(
            "create_calendar_event",
            '{"summary":"Interview","startAt":"2026-09-15T10:00:00",'
            '"endAt":"2026-09-15T11:00:00"}',
        )
    with pytest.raises(ValueError, match="after"):
        validateToolArguments(
            "create_calendar_event",
            '{"summary":"Interview","startAt":"2026-09-15T11:00:00+05:30",'
            '"endAt":"2026-09-15T10:00:00+05:30"}',
        )
