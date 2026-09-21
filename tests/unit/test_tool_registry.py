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
        "draft_gmail_message",
        "rename_drive_file",
        "request_gmail_approval",
        "revise_gmail_draft",
        "import_download_file",
        "forget_context",
        "remember_context",
        "propose_case",
        "search_calendar",
        "search_context",
        "search_documents",
        "search_downloads",
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


def testValidatesCopyOnlyDownloadImportPath():
    """The model cannot use the import tool to escape the sole allowlisted source root."""
    assert validateToolArguments(
        "import_download_file", '{"relativePath":"applications/resume.pdf"}'
    ) == {"relativePath": "applications/resume.pdf"}

    with pytest.raises(ValueError, match="relative"):
        validateToolArguments("import_download_file", '{"relativePath":"../secret.txt"}')
    with pytest.raises(ValueError, match="relative"):
        validateToolArguments("import_download_file", '{"relativePath":"/etc/passwd"}')


def testValidatesPersonalContextTools():
    """Model-selected context operations stay inside fixed categories and safe identifiers."""
    assert validateToolArguments(
        "remember_context",
        '{"category":"preferences","recordKey":"default-language","value":"English"}',
    ) == {
        "category": "preferences",
        "recordKey": "default-language",
        "value": "English",
    }
    assert validateToolArguments("search_context", '{"query":"language"}') == {
        "query": "language"
    }
    assert validateToolArguments(
        "forget_context", '{"recordId":"8c632bdd-e469-4b1a-a176-1f7a9cbd9a48"}'
    ) == {"recordId": "8c632bdd-e469-4b1a-a176-1f7a9cbd9a48"}

    with pytest.raises(ValueError, match="category"):
        validateToolArguments(
            "remember_context",
            '{"category":"secrets","recordKey":"token","value":"hidden"}',
        )
    with pytest.raises(ValueError, match="key"):
        validateToolArguments(
            "remember_context",
            '{"category":"preferences","recordKey":"../escape","value":"bad"}',
        )


def testValidatesNaturalCaseProposalArguments():
    """Case proposals require a bounded title and a concrete objective."""
    assert validateToolArguments(
        "propose_case",
        '{"title":"Software job search","objective":"Secure a software development role"}',
    ) == {
        "title": "Software job search",
        "objective": "Secure a software development role",
    }

    with pytest.raises(ValueError, match="title"):
        validateToolArguments(
            "propose_case",
            '{"title":"","objective":"Secure a software development role"}',
        )
    with pytest.raises(ValueError, match="objective"):
        validateToolArguments(
            "propose_case",
            '{"title":"Software job search","objective":""}',
        )


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
        "revise_gmail_draft",
        '{"draftId":"draft-1","expectedVersion":2,"accountKey":"work",'
        '"to":["person@example.com"],"subject":"Hello again","body":"Updated"}',
    )["expectedVersion"] == 2
    assert validateToolArguments(
        "request_gmail_approval",
        '{"draftId":"draft-1","draftVersion":2,"accountKey":"work",'
        '"to":["person@example.com"],"subject":"Hello again","body":"Updated"}',
    )["draftId"] == "draft-1"
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
