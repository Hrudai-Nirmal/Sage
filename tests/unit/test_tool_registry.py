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
        "add_case_milestone",
        "add_case_note",
        "archive_work_item",
        "delete_calendar_event",
        "delete_drive_file",
        "draft_gmail_message",
        "rename_drive_file",
        "request_gmail_approval",
        "revise_gmail_draft",
        "import_download_file",
        "forget_context",
        "get_case_details",
        "remember_context",
        "remember_email_watch",
        "research_web",
        "respond",
        "propose_case",
        "propose_schedule",
        "propose_task",
        "search_calendar",
        "search_context",
        "search_documents",
        "search_downloads",
        "search_drive",
        "search_gmail",
        "search_work_items",
        "send_gmail_message",
        "update_case_milestone",
        "update_calendar_event",
        "update_work_item",
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
        '{"category":"preferences","recordKey":"default-language","value":"English",'
        '"evidenceText":"I prefer English"}',
    ) == {
        "category": "preferences",
        "recordKey": "default-language",
        "value": "English",
        "evidenceText": "I prefer English",
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
        '{"title":"Software job search","objective":"Secure a software development role",'
        '"evidenceText":"Create a case for my software job search"}',
    ) == {
        "title": "Software job search",
        "objective": "Secure a software development role",
        "evidenceText": "Create a case for my software job search",
    }

    with pytest.raises(ValueError, match="title"):
        validateToolArguments(
            "propose_case",
            '{"title":"","objective":"Secure a software development role"}',
        )


def testValidatesTaskAndScheduleProposalArguments():
    """Natural work proposals carry complete bounded fields and exact intent evidence."""
    assert validateToolArguments(
        "propose_task",
        '{"title":"Submit application","description":"Apply to Acme",'
        '"priority":"HIGH","dueAt":"2026-09-30T18:00:00+05:30",'
        '"recurrence":null,"evidenceText":"Create a task to submit my Acme application"}',
    ) == {
        "title": "Submit application",
        "description": "Apply to Acme",
        "priority": "HIGH",
        "dueAt": "2026-09-30T18:00:00+05:30",
        "recurrence": None,
        "evidenceText": "Create a task to submit my Acme application",
    }
    assert validateToolArguments(
        "propose_schedule",
        '{"title":"Morning plan","prompt":"Summarize my open tasks",'
        '"kind":"REPORT","dueAt":"2026-09-30T09:00:00+05:30",'
        '"recurrence":"DAILY","evidenceText":"Schedule a daily morning plan"}',
    )["kind"] == "REPORT"

    with pytest.raises(ValueError, match="timezone"):
        validateToolArguments(
            "propose_schedule",
            '{"title":"Morning plan","prompt":"Summarize tasks","kind":"REPORT",'
            '"dueAt":"2026-09-30T09:00:00","recurrence":"DAILY",'
            '"evidenceText":"Schedule a daily morning plan"}',
        )


def testValidatesWorkLifecycleArguments():
    """One deep lifecycle interface validates fields against the selected work-item kind."""
    assert validateToolArguments(
        "search_work_items", '{"workItemKind":"TASK","query":"application"}'
    ) == {"workItemKind": "TASK", "query": "application"}
    assert validateToolArguments(
        "get_case_details", '{"caseId":"case-1"}'
    ) == {"caseId": "case-1"}
    assert validateToolArguments(
        "update_work_item",
        '{"workItemKind":"TASK","workItemId":"task-1","status":"COMPLETED",'
        '"priority":"HIGH","evidenceText":"Mark my application task complete"}',
    ) == {
        "workItemKind": "TASK",
        "workItemId": "task-1",
        "changes": {"status": "COMPLETED", "priority": "HIGH"},
        "evidenceText": "Mark my application task complete",
    }
    assert validateToolArguments(
        "add_case_note",
        '{"caseId":"case-1","text":"Applied to Acme",'
        '"evidenceText":"Add a note that I applied to Acme"}',
    )["caseId"] == "case-1"
    assert validateToolArguments(
        "add_case_milestone",
        '{"caseId":"case-1","title":"Complete interview","dueAt":null,'
        '"evidenceText":"Add complete interview as a milestone"}',
    )["title"] == "Complete interview"
    assert validateToolArguments(
        "update_case_milestone",
        '{"caseId":"case-1","milestoneId":"milestone-1","status":"COMPLETED",'
        '"evidenceText":"Mark the interview milestone complete"}',
    )["changes"] == {"status": "COMPLETED"}
    assert validateToolArguments(
        "archive_work_item",
        '{"workItemKind":"CASE","workItemId":"case-1","title":"Job search",'
        '"evidenceText":"Archive my job search case"}',
    )["workItemKind"] == "CASE"

    with pytest.raises(ValueError, match="Task"):
        validateToolArguments(
            "update_work_item",
            '{"workItemKind":"TASK","workItemId":"task-1","objective":"Invalid",'
            '"evidenceText":"Update the task"}',
        )
    with pytest.raises(ValueError, match="objective"):
        validateToolArguments(
            "propose_case",
            '{"title":"Software job search","objective":""}',
        )


def testValidatesStructuredEmailWatchArguments():
    """Email watch rules contain only a stable key, label, and bounded match phrases."""
    assert validateToolArguments(
        "remember_email_watch",
        '{"recordKey":"hm-restock","label":"H&M restock",'
        '"requiredTerms":["H&M","restock"],'
        '"evidenceText":"If I get an H&M restock email, notify me"}',
    ) == {
        "recordKey": "hm-restock",
        "label": "H&M restock",
        "requiredTerms": ["H&M", "restock"],
        "evidenceText": "If I get an H&M restock email, notify me",
    }

    with pytest.raises(ValueError, match="terms"):
        validateToolArguments(
            "remember_email_watch",
            '{"recordKey":"hm-restock","label":"H&M restock","requiredTerms":[],'
            '"evidenceText":"notify me"}',
        )
    with pytest.raises(ValueError, match="key"):
        validateToolArguments(
            "remember_email_watch",
            '{"recordKey":"../escape","label":"H&M restock",'
            '"requiredTerms":["H&M","restock"],"evidenceText":"notify me"}',
        )


def testValidatesTypedConversationResponse():
    """Ordinary conversation is an explicit typed model decision, not unstructured output."""
    assert validateToolArguments("respond", '{"text":"Hello, chief."}') == {
        "text": "Hello, chief."
    }

    with pytest.raises(ValueError, match="response"):
        validateToolArguments("respond", '{"text":""}')


def testValidatesSemanticResearchRequest():
    """Online research is selected through the same closed semantic gateway."""
    assert validateToolArguments(
        "research_web", '{"query":"current MLX releases"}'
    ) == {"query": "current MLX releases"}

    with pytest.raises(ValueError, match="query"):
        validateToolArguments("research_web", '{"query":""}')


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
