"""Test Sage's model-visible capability contracts and argument boundary."""

import pytest

from sage_core.tool_registry import getToolDefinitions, validateToolArguments


def testRegistryExposesOnlyImplementedGoogleTools():
    """The model can select real tools without inventing unavailable capabilities."""
    toolNames = {
        tool["function"]["name"] for tool in getToolDefinitions()
    }

    assert toolNames == {
        "create_drive_folder",
        "delete_drive_file",
        "rename_drive_file",
        "search_calendar",
        "search_drive",
        "search_gmail",
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
