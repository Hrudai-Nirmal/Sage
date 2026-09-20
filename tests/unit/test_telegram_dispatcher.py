"""Unit tests for Sage's native Telegram dispatcher failure boundaries."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError

import pytest


def testDispatcherDatabaseContextClosesConnection(tmp_path, monkeypatch):
    """The persistent worker must not retain one SQLite descriptor per loop."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherDatabase", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", tmp_path / "sage.db")

    with dispatcher.connectDatabase() as connection:
        connection.execute("CREATE TABLE health_check (id INTEGER)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def testCompletesAppliedCallbackWhenTelegramAcknowledgementExpired(tmp_path, monkeypatch):
    """An expired Telegram spinner must not leave an already-applied callback processing."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcher", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE telegram_callbacks (
                callback_id TEXT PRIMARY KEY, approval_id TEXT, action TEXT,
                sender_id INTEGER, status TEXT, received_at TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO telegram_callbacks VALUES ('old-callback', 'approval-1', 'APPROVE', 7, 'PENDING', 'now')"
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    def fakePostJson(url, payload, headers):
        if url.endswith("/answerCallbackQuery"):
            raise HTTPError(url, 400, "expired", {}, None)
        return {}

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)

    assert dispatcher.dispatchNextCallback(
        {
            "SAGE_APPROVAL_TOKEN": "approval",
            "SAGE_TELEGRAM_CHAT_ID": "-1001",
            "SAGE_TELEGRAM_MAIN_TOPIC_ID": "5",
            "TELEGRAM_BOT_TOKEN": "bot",
        }
    )
    with sqlite3.connect(databasePath) as connection:
        callbackStatus = connection.execute(
            "SELECT status FROM telegram_callbacks WHERE callback_id = 'old-callback'"
        ).fetchone()[0]
    assert callbackStatus == "COMPLETE"


def testRecoversInterruptedDispatcherClaims(tmp_path, monkeypatch):
    """A service restart must return abandoned claims to the single-worker queue."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherRecovery", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute("CREATE TABLE telegram_callbacks (status TEXT)")
        connection.execute("CREATE TABLE telegram_messages (dispatch_status TEXT)")
        connection.execute("INSERT INTO telegram_callbacks VALUES ('PROCESSING')")
        connection.execute("INSERT INTO telegram_messages VALUES ('PROCESSING')")
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    dispatcher.recoverInterruptedWork()

    with sqlite3.connect(databasePath) as connection:
        assert connection.execute("SELECT status FROM telegram_callbacks").fetchone()[0] == "PENDING"
        assert connection.execute("SELECT dispatch_status FROM telegram_messages").fetchone()[0] == "PENDING"


def testRecognizesOnlyApprovedTelegramModeCommands():
    """Telegram can select the four approved modes but cannot request a restart."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherModes", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.getModeCommand("/normal") == "NORMAL"
    assert dispatcher.getModeCommand("/eco@Hrudai_bot") == "ECO"
    assert dispatcher.getModeCommand("/sleep please") == "SLEEP"
    assert dispatcher.getModeCommand("/shutdown") == "SHUTDOWN"
    assert dispatcher.getModeCommand("/restart") is None
    assert dispatcher.getModeCommand("please use eco") is None


def testReconcilesDashboardModeWithoutStartingDuplicateModels(monkeypatch):
    """A persisted local mode change controls each exact model launch agent once."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherReconcile", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    stateChanges = []
    monkeypatch.setattr(
        dispatcher,
        "setModelAgentState",
        lambda agentName, shouldRun: stateChanges.append((agentName, shouldRun)),
    )

    assert dispatcher.reconcileModeState("ECO", "NORMAL") == "ECO"
    assert stateChanges == [
        ("com.sage.model-sage", False),
        ("com.sage.model-iris", False),
    ]
    stateChanges.clear()
    assert dispatcher.reconcileModeState("ECO", "ECO") == "ECO"
    assert stateChanges == []


def testParsesExplicitScheduledDeliveryCommand():
    """Scheduled work has a deterministic approval-card command contract."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherSchedule", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.getScheduleProposal(
        "/schedule 2026-09-11T09:00:00+05:30 | REPORT | Morning plan | Summarize my tasks | DAILY"
    ) == {
        "dueAt": "2026-09-11T09:00:00+05:30",
        "kind": "REPORT",
        "prompt": "Summarize my tasks",
        "recurrence": "DAILY",
        "title": "Morning plan",
    }
    assert dispatcher.getScheduleProposal("/schedule tomorrow") is None


def testDispatchesScheduledNotificationToItsDedicatedTopic(monkeypatch):
    """A due notification completes only after Telegram accepts its topic delivery."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherDelivery", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    sentMessages = []

    class FakeScheduleRepository:
        def claimDueDelivery(self):
            return {
                "id": "delivery-1",
                "kind": "NOTIFICATION",
                "prompt": "Submit the form",
                "title": "Placement deadline",
            }

        def completeDelivery(self, deliveryId):
            assert deliveryId == "delivery-1"

        def failDelivery(self, deliveryId, errorType):
            raise AssertionError(f"Unexpected retry for {deliveryId}: {errorType}")

    monkeypatch.setattr(dispatcher, "getCurrentMode", lambda: "NORMAL")
    monkeypatch.setattr(
        dispatcher,
        "sendTelegramMessage",
        lambda secrets, text, replyMarkup=None, topicId=None: sentMessages.append(
            (text, topicId)
        ),
    )

    assert dispatcher.dispatchNextScheduledDelivery(
        {
            "SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID": "7",
            "SAGE_TELEGRAM_REPORTS_TOPIC_ID": "6",
        },
        FakeScheduleRepository(),
    )
    assert sentMessages == [("Placement deadline\n\nSubmit the form", 7)]


def testDispatchesCalendarReminderWithoutLoadingAnotherModel(monkeypatch):
    """A due Calendar reminder uses the existing worker and Notifications topic."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramCalendarReminder", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    calls = []

    class FakeGoogleJobs:
        def claimDueCalendarReminder(self):
            return {"accountKey": "personal-work", "eventId": "event-1", "text": "Upcoming event"}

        def completeCalendarReminder(self, accountKey, eventId):
            calls.append(("complete", accountKey, eventId))

        def failCalendarReminder(self, accountKey, eventId, errorType):
            raise AssertionError(errorType)

    monkeypatch.setattr(dispatcher, "getCurrentMode", lambda: "NORMAL")
    monkeypatch.setattr(
        dispatcher,
        "sendTelegramMessage",
        lambda secrets, text, replyMarkup=None, topicId=None: calls.append(("send", text, topicId)),
    )

    assert dispatcher.dispatchNextCalendarReminder(
        {"SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID": "7"}, FakeGoogleJobs()
    )
    assert calls == [
        ("send", "Upcoming event", 7),
        ("complete", "personal-work", "event-1"),
    ]


def testImportantEmailCreatesOneApprovalCardInNotifications(monkeypatch):
    """An explicit deadline gets an alert plus an independently approved task proposal."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramEmailTriage", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    sentMessages = []
    completed = []

    class FakeGoogleJobs:
        def claimEmailTriage(self):
            return {
                "accountKey": "college", "messageId": "message-1",
                "sender": "placements@example.edu", "subject": "Submit placement form",
                "snippet": "Deadline: Friday", "bodyText": "Submit by Friday", "labelIds": ["UNREAD"],
            }

        def completeEmailTriage(self, accountKey, messageId, classification):
            completed.append((accountKey, messageId, classification["category"]))

        def failEmailTriage(self, accountKey, messageId, errorType):
            raise AssertionError(errorType)

    monkeypatch.setattr(dispatcher, "getCurrentMode", lambda: "NORMAL")
    monkeypatch.setattr(dispatcher, "postJson", lambda url, payload, headers: {"id": "approval-1"})
    monkeypatch.setattr(
        dispatcher,
        "sendTelegramMessage",
        lambda secrets, text, replyMarkup=None, topicId=None: sentMessages.append(
            (text, replyMarkup, topicId)
        ),
    )

    assert dispatcher.dispatchNextEmailTriage(
        {"SAGE_PROPOSAL_TOKEN": "proposal", "SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID": "7"},
        FakeGoogleJobs(),
    )
    assert "Important email [PLACEMENT]" in sentMessages[0][0]
    assert sentMessages[0][1]["inline_keyboard"][0][0]["callback_data"] == "approve:approval-1"
    assert sentMessages[0][2] == 7
    assert completed == [("college", "message-1", "PLACEMENT")]


def testBuildsScheduledReportFromDurableOperationalContext(tmp_path, monkeypatch):
    """Scheduled reports receive current tasks and cases instead of inventing state."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherReport", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            "CREATE TABLE tasks (title TEXT, description TEXT, status TEXT, priority TEXT, due_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE cases (title TEXT, objective TEXT, status TEXT)"
        )
        connection.execute(
            "INSERT INTO tasks VALUES ('Submit form', 'Placement form', 'OPEN', 'HIGH', '2026-09-11')"
        )
        connection.execute(
            "INSERT INTO cases VALUES ('Placement', 'Secure an offer', 'ACTIVE')"
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    reportContext = dispatcher.buildScheduledContext()

    assert "Submit form" in reportContext
    assert "Placement" in reportContext
    assert "Only use this snapshot" in reportContext


def testRecognizesExplicitResearchCommand():
    """Online research is deliberate and never inferred from ordinary conversation."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherResearch", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.getResearchQuery("/research current MLX releases") == "current MLX releases"
    assert (
        dispatcher.getResearchQuery("Can you look for small sling bags under 1500")
        == "small sling bags under 1500"
    )
    assert dispatcher.getResearchQuery("Please search online for MLX releases") == "MLX releases"
    assert (
        dispatcher.getResearchQuery(
            "You can do that now try it",
            previousUserMessage="Can you look for small sling bags under 1500",
        )
        == "small sling bags under 1500"
    )
    assert dispatcher.getResearchQuery("what is new?") is None
    assert dispatcher.getResearchQuery("/research   ") is None


def testSearchesIndexedMailWithoutCallingGoogle(tmp_path, monkeypatch):
    """The Telegram mail command searches immutable local snapshots only."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherMail", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE email_messages (
                account_key TEXT, sender TEXT, subject TEXT, snippet TEXT,
                body_text TEXT, internal_date TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO email_messages VALUES (
                'personal-work', 'Placement Office <placements@example.edu>',
                'Interview Friday', 'Bring your resume', 'Room 201 at 10 AM',
                '1789092000000'
            )"""
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    assert dispatcher.getMailQuery("/mail@Hrudai_bot placement Friday") == "placement Friday"
    assert dispatcher.getMailQuery("/mail") == ""
    assert dispatcher.getMailQuery("show my mail") == ""
    assert dispatcher.getMailQuery("Check my mail for a recent H&M purchase") == "H&M purchase"
    assert (
        dispatcher.getMailQuery("Can you check for any mails regarding my recent H&M purchase")
        == "H&M purchase"
    )
    assert dispatcher.getMailQuery("Please check my Gmail") == ""
    assert (
        dispatcher.getMailQuery("Can you check for any recent notifications from neon and inngest")
        == "from:neon|from:inngest"
    )
    assert dispatcher.getMailQuery("Do I have any emails from Neon?") == "from:Neon"
    assert dispatcher.getMailQuery("Find emails about placements") == "placements"
    assert (
        dispatcher.getMailQuery("Look for any assessment links in my mails")
        == "assessment links"
    )
    assert dispatcher.getMailQuery("Search for invoices across my email") == "invoices"
    assert dispatcher.getMailQuery("Show me my inbox") == ""
    mailReply = dispatcher.formatMailSearch(dispatcher.searchIndexedMail("placement Friday"))

    assert "personal-work" in mailReply
    assert "Interview Friday" in mailReply
    assert "placements@example.edu" in mailReply
    assert "Room 201" in mailReply


def testSearchesAlternativeEmailSendersInsteadOfRequiringOneMessageToContainBoth(
    tmp_path, monkeypatch
):
    """A request for Neon and Inngest returns independent matching messages."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherMailAlternatives", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE email_messages (
                account_key TEXT, sender TEXT, subject TEXT, snippet TEXT,
                body_text TEXT, internal_date TEXT
            )"""
        )
        connection.executemany(
            "INSERT INTO email_messages VALUES (?, ?, ?, '', '', ?)",
            [
                ("work", "alerts@neon.tech", "Database usage alert", "1789092000002"),
                ("work", "notifications@inngest.com", "Function failed", "1789092000001"),
                ("personal", "newsletter@example.com", "Weekly digest", "1789092000000"),
            ],
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    messages = dispatcher.searchIndexedMail("from:neon|from:inngest")

    assert [message["subject"] for message in messages] == [
        "Database usage alert",
        "Function failed",
    ]


def testSearchesIndexedCalendarWithoutCallingGoogle(tmp_path, monkeypatch):
    """The Calendar command reads the latest monitored snapshot from SQLite."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherGoogle", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            "CREATE TABLE calendar_events (event_id TEXT, summary TEXT, description TEXT, location TEXT, start_at TEXT, end_at TEXT)"
        )
        connection.execute(
            "INSERT INTO calendar_events VALUES ('event-1', 'Placement interview', 'Technical round', 'Room 201', '2026-09-12T10:00:00+05:30', '2026-09-12T11:00:00+05:30')"
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    assert dispatcher.getLocalSearchCommand("/calendar placement") == ("calendar", "placement")
    assert dispatcher.getLocalSearchCommand("/drive handbook") is None
    events = dispatcher.searchIndexedCalendar("placement")

    assert events[0]["eventId"] == "event-1"
    assert "Placement interview" in dispatcher.formatCalendarSearch(events)


def testParsesExplicitLiveDriveCommandsWithoutGuessingWrites():
    """Search, folder creation, rename, and deletion have exact command contracts."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDriveCommands", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.getDriveCommand("/drive placement") == {"action": "SEARCH", "query": "placement"}
    assert dispatcher.getDriveCommand("/drive-folder work | Applications") == {
        "action": "CREATE_FOLDER", "accountKey": "work", "name": "Applications", "parentId": ""
    }
    assert dispatcher.getDriveCommand("/drive-rename personal | file_1 | Final.pdf") == {
        "action": "RENAME", "accountKey": "personal", "fileId": "file_1", "name": "Final.pdf"
    }
    assert dispatcher.getDriveCommand("/drive-delete college | file_2 | Draft.pdf") == {
        "action": "DELETE", "accountKey": "college", "fileId": "file_2", "name": "Draft.pdf"
    }
    assert dispatcher.getDriveCommand("rename something") is None


def testLiveDriveSearchCallsEveryAccountWebhook(monkeypatch):
    """An unqualified Drive query reads all four accounts live through n8n."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDriveLive", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    calls = []
    monkeypatch.setattr(
        dispatcher,
        "postJson",
        lambda url, payload, headers: calls.append((url, payload, headers)) or {"files": []},
    )

    assert dispatcher.searchLiveDrive({"SAGE_DRIVE_TOOL_TOKEN": "secret"}, "handbook") == []
    assert [call[0].rsplit("/", 1)[-1] for call in calls] == [
        "sage-drive-personal-work", "sage-drive-work", "sage-drive-personal", "sage-drive-college"
    ]
    assert all(call[1] == {"action": "SEARCH", "query": "handbook"} for call in calls)
    assert all(call[2]["X-Sage-Drive-Token"] == "secret" for call in calls)


def testBuildsRecentConversationWithoutCurrentMessageDuplication(tmp_path, monkeypatch):
    """Ordinary replies receive compact prior Telegram context in chronological order."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherHistory", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE telegram_messages (
                message_id INTEGER PRIMARY KEY, text TEXT, dispatch_status TEXT,
                reply_text TEXT
            )"""
        )
        connection.execute("INSERT INTO telegram_messages VALUES (1, 'first', 'COMPLETE', 'answer')")
        connection.execute("INSERT INTO telegram_messages VALUES (2, 'follow-up', 'PROCESSING', NULL)")
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    assert dispatcher.getRecentConversation(2, "follow-up") == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "follow-up"},
    ]


def testLoadsVersionedSagePrompt():
    """Telegram replies use the shared role contract instead of an inline identity fragment."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherPrompt", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    prompt = dispatcher.loadSystemPrompt("sage")

    assert prompt.startswith("# Sage system prompt")
    assert "explicit user approval" in prompt
    assert "Live capability manifest" in prompt
    assert "gmail.search" in prompt
    assert "gmail.draft" in prompt


def testToolExecutionReportsConfiguredCapabilityAfterRetryExhaustion(monkeypatch):
    """A transient outage is surfaced in chat without claiming the ability is absent."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramCapabilityFailure", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    monkeypatch.setattr(
        dispatcher,
        "executeCapability",
        lambda capabilityName, operation: (_ for _ in ()).throw(
            dispatcher.CapabilityExecutionError("gmail.search", 3)
        ),
    )
    modelMessages = []
    toolResults = dispatcher._appendExecutedToolCalls(
        modelMessages,
        {
            "role": "assistant",
            "tool_calls": [{
                "id": "mail-1",
                "function": {"name": "search_gmail", "arguments": '{"query":"assessment"}'},
            }],
        },
        [{
            "id": "mail-1",
            "function": {"name": "search_gmail", "arguments": '{"query":"assessment"}'},
        }],
        {},
        "Search my Gmail for assessments",
        "telegram:90",
        False,
    )

    assert toolResults == [{
        "attempts": 3,
        "capabilityId": "gmail.search",
        "status": "TEMPORARILY_UNAVAILABLE",
        "toolName": "search_gmail",
    }]
    assert dispatcher.getCapabilityFailureReply(toolResults) == (
        "Gmail search is configured, but it is temporarily unavailable after 3 technical "
        "attempts. No action was taken."
    )


def testExecutesModelSelectedGmailToolAgainstRealIndexBoundary(tmp_path, monkeypatch):
    """A structured Gmail call returns evidence instead of a capability denial."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramToolExecutor", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE email_messages (
                account_key TEXT, sender TEXT, subject TEXT, snippet TEXT,
                body_text TEXT, internal_date TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO email_messages VALUES (
                'work', 'alerts@neon.tech', 'Usage alert', 'Review usage',
                'Your project crossed its threshold', '1789092000000'
            )"""
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    toolResult = dispatcher.executeSageTool(
        {}, "search_gmail", '{"query":"from:Neon"}', "Check email from Neon"
    )

    assert toolResult["status"] == "COMPLETE"
    assert toolResult["source"] == "gmail-index"
    assert toolResult["results"][0]["subject"] == "Usage alert"


def testRejectsModelSelectedDriveMutationWithoutExplicitUserIntent(monkeypatch):
    """A tool call alone cannot authorize a Drive mutation absent a direct request."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramToolPolicy", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    monkeypatch.setattr(
        dispatcher,
        "requestLiveDrive",
        lambda *arguments, **keywordArguments: (_ for _ in ()).throw(
            AssertionError("Drive must not be called")
        ),
    )

    toolResult = dispatcher.executeSageTool(
        {"SAGE_DRIVE_TOOL_TOKEN": "secret"},
        "create_drive_folder",
        '{"accountKey":"work","name":"Applications"}',
        "What folders would help organize my applications?",
    )

    assert toolResult["status"] == "NEEDS_EXPLICIT_REQUEST"


def testToolAwareConversationExecutesCallAndSynthesizesEvidence(monkeypatch):
    """Ordinary language can invoke one real tool and return its grounded result."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramToolLoop", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    modelPayloads = []

    def fakePostJson(url, payload, headers):
        modelPayloads.append(payload)
        if len(modelPayloads) == 1:
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "search_gmail", "arguments": '{"query":"from:Neon"}'},
                        }],
                    }
                }]
            }
        return {"choices": [{"message": {"content": "No matching Neon email was found."}}]}

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)
    def fakeExecuteTool(
        secrets,
        toolName,
        rawArguments,
        userMessage,
        requestKey="",
        hasExplicitGmailProposalIntent=False,
    ):
        return {"status": "COMPLETE", "source": "gmail-index", "results": []}

    monkeypatch.setattr(dispatcher, "executeSageTool", fakeExecuteTool)

    reply = dispatcher.runToolAwareConversation(
        {"SAGE_MODEL_API_KEY": "model"},
        [{"role": "user", "content": "Check if Neon emailed me"}],
        "Check if Neon emailed me",
    )

    assert reply == "No matching Neon email was found."
    assert modelPayloads[0]["tools"]
    assert modelPayloads[1]["messages"][-1]["role"] == "tool"
    assert modelPayloads[1]["messages"][-1]["tool_call_id"] == "call-1"


def testReadSourceInferenceForcesOneSourceAndAsksWhenMultiple(monkeypatch):
    """Sage may infer a named read source but cannot silently choose between two."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramReadInference", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    modelPayloads = []

    def fakePostJson(url, payload, headers):
        modelPayloads.append(payload)
        if len(modelPayloads) > 1:
            return {"choices": [{"message": {"content": "No matching email was found."}}]}
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "mail-read",
                        "function": {"name": "search_gmail", "arguments": '{"query":"assessment"}'},
                    }],
                }
            }]
        }

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)
    monkeypatch.setattr(
        dispatcher,
        "executeSageTool",
        lambda *arguments, **keywordArguments: {
            "status": "COMPLETE",
            "source": "gmail-index",
            "results": [],
        },
    )

    dispatcher.runToolAwareConversation(
        {"SAGE_MODEL_API_KEY": "model"},
        [{"role": "user", "content": "Search Gmail for assessment links"}],
        "Search Gmail for assessment links",
    )
    ambiguousReply = dispatcher.runToolAwareConversation(
        {"SAGE_MODEL_API_KEY": "model"},
        [{"role": "user", "content": "Search Gmail and Drive for assessment links"}],
        "Search Gmail and Drive for assessment links",
    )

    assert modelPayloads[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "search_gmail"},
    }
    assert ambiguousReply == "Which source should I search: Gmail, Google Drive?"


def testFalseCapabilityDenialFallsBackToGroundedToolEvidence(monkeypatch):
    """A model denial after a successful Gmail search is replaced with deterministic results."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDenialFence", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    toolResults = [{
        "status": "COMPLETE",
        "toolName": "search_gmail",
        "results": [{
            "accountKey": "work",
            "sender": "assessments@example.com",
            "subject": "Assessment link",
            "snippet": "Open the assessment",
            "bodyText": "https://example.com/assessment",
            "internalDate": "1789092000000",
        }],
    }]

    reply = dispatcher.getCapabilityDenialFallback(
        "I cannot access your Gmail inbox.", toolResults
    )

    assert reply is not None
    assert "Assessment link" in reply
    assert "work" in reply
    assert "cannot access" not in reply


def testStandingInstructionIsExplicitContextWriteIntent():
    """An explicit always/from-now-on directive can be persisted without a magic phrase."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramStandingRule", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.hasExplicitContextWriteIntent(
        "Always notify me about placement-related emails"
    )
    assert dispatcher.hasExplicitContextWriteIntent(
        "From now on, use DD/MM/YYYY dates"
    )
    assert not dispatcher.hasExplicitContextWriteIntent(
        "I always read placement emails in the morning"
    )


def testUngroundedPreferenceSaveClaimIsRejected():
    """Model wording cannot manufacture a context-write receipt."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramContextReceipt", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    fallback = dispatcher.getUngroundedContextWriteFallback(
        "I've updated your preferences to prioritize placement emails.", []
    )
    groundedFallback = dispatcher.getUngroundedContextWriteFallback(
        "I've updated your preferences.",
        [{"status": "COMPLETE", "toolName": "remember_context"}],
    )

    assert fallback is not None
    assert "not saved" in fallback
    assert groundedFallback is None


def testParsesExplicitContextCommandsWithoutGuessingFields():
    """Telegram offers deterministic inspect, remember, correct, and forget operations."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramContextCommands", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.getContextCommand("/context language") == {
        "action": "SEARCH",
        "query": "language",
    }
    assert dispatcher.getContextCommand(
        "/remember preferences | default-language | English"
    ) == {
        "action": "REMEMBER",
        "category": "preferences",
        "recordKey": "default-language",
        "value": "English",
    }
    assert dispatcher.getContextCommand("/correct record-1 | Updated") == {
        "action": "CORRECT",
        "recordId": "record-1",
        "value": "Updated",
    }
    assert dispatcher.getContextCommand("/forget record-1") == {
        "action": "FORGET",
        "recordId": "record-1",
    }
    assert dispatcher.getContextCommand("/remember preferences | missing value") is None


def testContextToolUsesDirectStandardWriteAndApprovalForSensitiveWrite(monkeypatch):
    """The executor, not the model, chooses the context authority path by category."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramContextTools", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    postedPayloads = []
    approvalCalls = []

    def fakePostJson(url, payload, headers):
        postedPayloads.append((url, payload, headers))
        return {
            "category": payload["category"],
            "id": "context-1",
            "key": payload["recordKey"],
            "sensitivity": "STANDARD",
            "sourceRef": payload["sourceRef"],
            "sourceType": payload["sourceType"],
            "updatedAt": "2026-09-19T00:00:00+00:00",
            "value": payload["value"],
            "version": 1,
        }

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)
    monkeypatch.setattr(
        dispatcher,
        "getContextVersion",
        lambda category, recordKey: 0,
    )
    monkeypatch.setattr(
        dispatcher,
        "sendApprovalRequest",
        lambda secrets, actionType, payload, label, idempotencyKey="": approvalCalls.append(
            (actionType, payload, label, idempotencyKey)
        ) or "Approval card sent.",
    )

    standardResult = dispatcher.executeSageTool(
        {"SAGE_PROPOSAL_TOKEN": "proposal"},
        "remember_context",
        '{"category":"preferences","recordKey":"language","value":"English"}',
        "Remember that my language is English",
        "telegram:301",
    )
    sensitiveResult = dispatcher.executeSageTool(
        {"SAGE_PROPOSAL_TOKEN": "proposal"},
        "remember_context",
        '{"category":"identity","recordKey":"legal-name","value":"Test User"}',
        "Remember that my legal name is Test User",
        "telegram:302",
    )

    assert standardResult["status"] == "COMPLETE"
    assert postedPayloads[0][1]["sourceRef"] == "telegram:301"
    assert sensitiveResult == {
        "status": "PENDING_APPROVAL",
        "result": "Approval card sent.",
    }
    assert approvalCalls[0][0] == "UPSERT_CONTEXT_RECORD"
    assert approvalCalls[0][1]["expectedVersion"] == 0


def testConfirmedContextIsInjectedIntoEveryOrdinaryModelTurn(tmp_path, monkeypatch):
    """Context relevance is deterministic and does not depend on the model remembering it."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramContextPrompt", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    dataRoot = tmp_path / "SageData"
    databasePath = dataRoot / "database" / "sage.db"
    monkeypatch.setattr(dispatcher, "DATA_ROOT", dataRoot)
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)
    repository = dispatcher.ContextStateRepository(
        dispatcher.SageDatabase(databasePath), dataRoot
    )
    repository.upsertRecord(
        category="preferences",
        recordKey="default-language",
        value="English",
        sourceType="telegram-explicit",
        sourceRef="telegram:303",
        actor="telegram-user:8961856168",
    )
    modelPayloads = []

    def fakePostJson(url, payload, headers):
        modelPayloads.append(payload)
        return {"choices": [{"message": {"content": "Hello"}}]}

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)

    dispatcher.runToolAwareConversation(
        {"SAGE_MODEL_API_KEY": "model"},
        [{"role": "user", "content": "What language should you use?"}],
        "What language should you use?",
    )

    assert "Confirmed personal context" in modelPayloads[0]["messages"][0]["content"]
    assert "default-language: English" in modelPayloads[0]["messages"][0]["content"]


def testToolAwareConversationCanSearchThenMutateAnExactCalendarEvent(monkeypatch):
    """A second bounded tool round can use a search result's exact Calendar event ID."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramMultiToolLoop", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    modelCallCount = 0
    executedTools = []

    def fakePostJson(url, payload, headers):
        nonlocal modelCallCount
        modelCallCount += 1
        if modelCallCount == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "search-1", "type": "function", "function": {
                    "name": "search_calendar", "arguments": '{"query":"Interview"}'
                }
            }]}}]}
        if modelCallCount == 2:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "update-1", "type": "function", "function": {
                    "name": "update_calendar_event",
                    "arguments": '{"eventId":"event-1","summary":"Updated interview"}',
                }
            }]}}]}
        return {"choices": [{"message": {"content": "The Calendar update is queued."}}]}

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)
    def fakeExecuteTool(
        secrets,
        toolName,
        rawArguments,
        userMessage,
        requestKey="",
        hasExplicitGmailProposalIntent=False,
    ):
        executedTools.append(toolName)
        return {"status": "COMPLETE"}

    monkeypatch.setattr(dispatcher, "executeSageTool", fakeExecuteTool)

    reply = dispatcher.runToolAwareConversation(
        {"SAGE_MODEL_API_KEY": "model"},
        [{"role": "user", "content": "Rename my Interview calendar event"}],
        "Rename my Interview calendar event",
        "telegram:9",
    )

    assert reply == "The Calendar update is queued."
    assert executedTools == ["search_calendar", "update_calendar_event"]
    assert modelCallCount == 3


def testCalendarCreateQueuesDurablyOnlyForExplicitRequest(monkeypatch):
    """An explicit Calendar create is queued; advisory conversation cannot mutate it."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramCalendarCreate", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    queuedActions = []
    monkeypatch.setattr(
        dispatcher,
        "queueGoogleAction",
        lambda actionType, accountKey, payload, requestKey: queuedActions.append(
            (actionType, accountKey, payload, requestKey)
        ) or {"id": "action-1", "status": "PENDING"},
    )
    arguments = (
        '{"summary":"Interview","startAt":"2026-09-15T10:00:00+05:30",'
        '"endAt":"2026-09-15T11:00:00+05:30"}'
    )

    rejectedResult = dispatcher.executeSageTool(
        {}, "create_calendar_event", arguments, "What time is best for an interview?", "msg-1"
    )
    queuedResult = dispatcher.executeSageTool(
        {}, "create_calendar_event", arguments, "Create a calendar event for the interview", "msg-2"
    )
    updatedResult = dispatcher.executeSageTool(
        {},
        "update_calendar_event",
        '{"eventId":"event-1","summary":"Updated interview"}',
        "Rename my Interview calendar event to Updated interview",
        "msg-3",
    )

    assert rejectedResult["status"] == "NEEDS_EXPLICIT_REQUEST"
    assert queuedResult["status"] == "QUEUED"
    assert updatedResult["status"] == "QUEUED"
    assert queuedActions[0][0] == "CREATE_CALENDAR_EVENT"
    assert queuedActions[0][2]["eventId"]
    assert queuedActions[1][0] == "UPDATE_CALENDAR_EVENT"


def testGmailSendAlwaysCreatesApprovalInsteadOfCallingGoogle(monkeypatch):
    """Even explicit send wording can only create a Telegram approval proposal."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramGmailSend", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    proposals = []
    monkeypatch.setattr(
        dispatcher,
        "sendApprovalRequest",
        lambda secrets, actionType, payload, label, idempotencyKey="": proposals.append(
            (actionType, payload, label)
        ) or "Approval card sent.",
    )

    draftOnlyResult = dispatcher.executeSageTool(
        {},
        "send_gmail_message",
        '{"accountKey":"work","to":["person@example.com"],"subject":"Hello","body":"Hi"}',
        "Help me draft an email to this person",
        "msg-2",
    )
    toolResult = dispatcher.executeSageTool(
        {},
        "send_gmail_message",
        '{"accountKey":"work","to":["person@example.com"],"subject":"Hello","body":"Hi"}',
        "Send this email now",
        "msg-3",
    )
    mismatchedRecipientResult = dispatcher.executeSageTool(
        {},
        "send_gmail_message",
        '{"accountKey":"work","to":["typo@example.com"],"subject":"Hello","body":"Hi"}',
        "Send this email to person@example.com now",
        "msg-4",
    )
    contextualMismatchResult = dispatcher.executeSageTool(
        {},
        "send_gmail_message",
        '{"accountKey":"work","to":["typo@example.com"],"subject":"Hello","body":"Hi"}',
        "It is person@example.com; request the approval again",
        "msg-5",
        hasExplicitGmailProposalIntent=True,
    )

    assert draftOnlyResult["status"] == "NEEDS_EXPLICIT_REQUEST"
    assert toolResult["status"] == "PENDING_APPROVAL"
    assert mismatchedRecipientResult["status"] == "REJECTED"
    assert mismatchedRecipientResult["error"] == "The proposed recipients differ from the request."
    assert contextualMismatchResult["status"] == "REJECTED"
    assert proposals[0][0] == "SEND_GMAIL_MESSAGE"
    assert len(proposals) == 1


def testEmailDraftToolsPersistReviseAndRequestExactApproval(monkeypatch):
    """Telegram drafting stays reversible until the exact saved version gets a card."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramEmailDrafts", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    coreCalls = []
    proposals = []

    def fakePostJson(url, payload, headers):
        coreCalls.append((url, payload))
        return {
            **{key: value for key, value in payload.items() if key != "expectedVersion"},
            "id": "draft-1",
            "version": 2 if url.endswith("/versions") else 1,
            "status": "DRAFT",
        }

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)
    monkeypatch.setattr(
        dispatcher,
        "sendApprovalRequest",
        lambda secrets, actionType, payload, label, idempotencyKey="": proposals.append(
            (actionType, payload, label, idempotencyKey)
        ) or "Approval card sent.",
    )
    message = {
        "accountKey": "work",
        "to": ["person@example.com"],
        "subject": "Hello",
        "body": "Hi",
    }

    drafted = dispatcher.executeSageTool(
        {"SAGE_PROPOSAL_TOKEN": "token"},
        "draft_gmail_message",
        json.dumps(message),
        "Draft an email to person@example.com",
        "msg-10",
    )
    revised = dispatcher.executeSageTool(
        {"SAGE_PROPOSAL_TOKEN": "token"},
        "revise_gmail_draft",
        json.dumps({**message, "draftId": "draft-1", "expectedVersion": 1, "body": "Hello"}),
        "Change the body to Hello",
        "msg-11",
    )
    requested = dispatcher.executeSageTool(
        {},
        "request_gmail_approval",
        json.dumps({**message, "draftId": "draft-1", "draftVersion": 2, "body": "Hello"}),
        "Looks good, please send it",
        "msg-12",
        hasExplicitGmailProposalIntent=True,
    )

    assert drafted["status"] == "DRAFTED"
    assert revised["draft"]["version"] == 2
    assert requested["status"] == "PENDING_APPROVAL"
    assert coreCalls[0][0].endswith("/v1/email-drafts")
    assert coreCalls[1][0].endswith("/v1/email-drafts/draft-1/versions")
    assert proposals[0][1]["draftVersion"] == 2


def testSavedDraftReplyCarriesIdentityAndNaturalConfirmationReusesIt():
    """A later confirmation should target the saved version instead of creating a duplicate."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramSavedDraft", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    reply = dispatcher.getDraftedReply(
        [{
            "status": "DRAFTED",
            "draft": {
                "id": "draft-1",
                "version": 2,
                "accountKey": "work",
                "to": ["person@example.com"],
                "subject": "Hello",
                "body": "Updated body",
            },
        }]
    )

    assert reply is not None
    assert "Draft ID: draft-1" in reply
    assert "Version: 2" in reply
    assert dispatcher.getSavedDraftIdentity(
        [{"role": "assistant", "content": reply}]
    ) == ("draft-1", 2)
    assert dispatcher.hasConfirmedGmailDraft(
        [{"role": "assistant", "content": reply}], "Sure, looks good"
    )


def testConfirmedEmailDraftForcesTrustedApprovalProposal(monkeypatch):
    """A contextual confirmation must open the button flow instead of another chat loop."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramConfirmedEmail", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    modelPayloads = []
    executedTools = []

    def fakePostJson(url, payload, headers):
        modelPayloads.append(payload)
        if len(modelPayloads) == 1:
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "send-1",
                            "type": "function",
                            "function": {
                                "name": "send_gmail_message",
                                "arguments": (
                                    '{"accountKey":"work","to":["friend@example.com"],'
                                    '"subject":"Party invitation","body":"Join me at 7 PM."}'
                                ),
                            },
                        }],
                    }
                }]
            }
        return {"choices": [{"message": {"content": "Approval card sent."}}]}

    def fakeExecuteSageTool(
        secrets,
        toolName,
        rawArguments,
        userMessage,
        requestKey="",
        hasExplicitGmailProposalIntent=False,
    ):
        executedTools.append((toolName, hasExplicitGmailProposalIntent))
        return {"status": "PENDING_APPROVAL", "result": "Approval card sent."}

    monkeypatch.setattr(dispatcher, "postJson", fakePostJson)
    monkeypatch.setattr(dispatcher, "executeSageTool", fakeExecuteSageTool)
    conversation = [
        {
            "role": "user",
            "content": "Draft an email from my work mail inviting friend@example.com to a party.",
        },
        {
            "role": "assistant",
            "content": (
                "**To:** friend@example.com\n**Subject:** Party invitation\n\n"
                "Join me at 7 PM. Please confirm if you would like me to send it."
            ),
        },
        {"role": "user", "content": "Yes"},
    ]

    reply = dispatcher.runToolAwareConversation(
        {"SAGE_MODEL_API_KEY": "model"},
        conversation,
        "Yes",
        "telegram:60",
    )

    assert reply == "Approval card sent."
    assert modelPayloads[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "send_gmail_message"},
    }
    assert len(modelPayloads) == 1
    assert executedTools == [("send_gmail_message", True)]


def testGmailDraftConfirmationAcceptsNaturalLanguageButRejectsHesitation():
    """Approval-card intent should be conversational without treating uncertainty as consent."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramNaturalApproval", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    conversation = [
        {"role": "user", "content": "Draft an email to friend@example.com."},
        {
            "role": "assistant",
            "content": "**To:** friend@example.com\n**Subject:** Dinner\n\nDinner at 8?",
        },
        {"role": "user", "content": "I did not see an approval card."},
        {
            "role": "assistant",
            "content": "I can request the email approval buttons again when you are ready.",
        },
    ]

    for naturalConfirmation in (
        "Sure, that looks good",
        "Okay, please do it",
        "Yep 👍",
        "All good, go for it",
        "Works for me",
        "Perfect",
        "Please send",
        "Can you show the approval buttons again?",
        "Re-request approval for that",
    ):
        assert dispatcher.hasConfirmedGmailDraft(conversation, naturalConfirmation)
    for hesitantReply in ("Not yet", "Maybe later", "Wait, change the time first"):
        assert not dispatcher.hasConfirmedGmailDraft(conversation, hesitantReply)


def testGoogleActionWorkerStagesGmailDraftBeforeSending(monkeypatch):
    """The worker persists a Gmail draft ID before a later send attempt."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramGoogleWorker", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    class FakeRepository:
        def __init__(self):
            self.staged = []
            self.completed = []
            self.failed = []

        def claimPendingAction(self):
            return {
                "id": "action-1",
                "actionType": "SEND_GMAIL_MESSAGE",
                "accountKey": "work",
                "payload": {
                    "to": ["person@example.com"],
                    "subject": "Hello",
                    "body": "Hi",
                },
                "stage": "CREATE_DRAFT",
                "remoteId": "",
            }

        def stageGmailDraft(self, actionId, draftId):
            self.staged.append((actionId, draftId))

        def completeAction(self, actionId, remoteId=""):
            self.completed.append((actionId, remoteId))

        def failAction(self, actionId, errorType):
            self.failed.append((actionId, errorType))

    actionRepository = FakeRepository()
    calls = []
    monkeypatch.setattr(dispatcher, "getCurrentMode", lambda: "NORMAL")
    monkeypatch.setattr(
        dispatcher,
        "requestGoogleAction",
        lambda secrets, action: calls.append(action) or {"id": "draft-1"},
    )
    monkeypatch.setattr(
        dispatcher,
        "sendTelegramMessage",
        lambda *arguments, **keywordArguments: (_ for _ in ()).throw(
            AssertionError("Draft staging must not announce an unsent email")
        ),
    )

    assert dispatcher.dispatchNextGoogleAction({}, actionRepository)
    assert calls[0]["stage"] == "CREATE_DRAFT"
    assert actionRepository.staged == [("action-1", "draft-1")]
    assert actionRepository.completed == []


def testGoogleActionWorkerCompletesCalendarMutationAndNotifies(monkeypatch):
    """A successful Calendar API result completes and announces the durable action."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramCalendarWorker", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    class FakeRepository:
        def __init__(self):
            self.completed = []

        def claimPendingAction(self):
            return {
                "id": "action-2",
                "actionType": "CREATE_CALENDAR_EVENT",
                "accountKey": "personal-work",
                "payload": {"eventId": "event-1", "summary": "Interview"},
                "stage": "EXECUTE",
                "remoteId": "",
            }

        def completeAction(self, actionId, remoteId=""):
            self.completed.append((actionId, remoteId))

        def failAction(self, actionId, errorType):
            raise AssertionError(errorType)

    actionRepository = FakeRepository()
    notifications = []
    monkeypatch.setattr(dispatcher, "getCurrentMode", lambda: "NORMAL")
    monkeypatch.setattr(
        dispatcher, "requestGoogleAction", lambda secrets, action: {"id": "event-1"}
    )
    monkeypatch.setattr(
        dispatcher,
        "sendTelegramMessage",
        lambda secrets, text, **options: notifications.append((text, options)),
    )

    assert dispatcher.dispatchNextGoogleAction(
        {"SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID": "12"}, actionRepository
    )
    assert actionRepository.completed == [("action-2", "event-1")]
    assert "Created Calendar event" in notifications[0][0]


def testSearchesDownloadsAndImportsOnlyThroughCoreCopyBoundary(tmp_path, monkeypatch):
    """Telegram file work discovers host paths but imports through the managed registry API."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDocumentTools", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    downloadsRoot = tmp_path / "Downloads"
    downloadsRoot.mkdir()
    (downloadsRoot / "Resume.pdf").write_bytes(b"resume")
    monkeypatch.setattr(dispatcher, "DOWNLOADS_ROOT", downloadsRoot)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE documents (
                id TEXT, canonical_name TEXT, original_name TEXT,
                source_relative_path TEXT, checksum TEXT, imported_at TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO documents VALUES (
                'document-0', 'Resume-def.pdf', 'Resume.pdf', 'Resume.pdf',
                'def', '2026-09-13T00:00:00+00:00'
            )"""
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)
    calls = []
    monkeypatch.setattr(
        dispatcher,
        "postJson",
        lambda url, payload, headers: calls.append((url, payload, headers)) or {
            "id": "document-1", "name": "Resume-abc.pdf", "path": "/managed/Resume-abc.pdf",
            "checksum": "abc",
        },
    )

    searchResult = dispatcher.executeSageTool(
        {}, "search_downloads", '{"query":"resume"}', "Find my resume in Downloads"
    )
    registeredResult = dispatcher.executeSageTool(
        {}, "search_documents", '{"query":"resume"}', "Find my registered resume"
    )
    rejectedImport = dispatcher.executeSageTool(
        {}, "import_download_file", '{"relativePath":"Resume.pdf"}', "Where is my resume?"
    )
    importResult = dispatcher.executeSageTool(
        {"SAGE_PROPOSAL_TOKEN": "proposal"},
        "import_download_file",
        '{"relativePath":"Resume.pdf"}',
        "Import Resume.pdf from Downloads into Sage",
    )

    assert searchResult["results"][0]["relativePath"] == "Resume.pdf"
    assert registeredResult["results"][0]["id"] == "document-0"
    assert rejectedImport["status"] == "NEEDS_EXPLICIT_REQUEST"
    assert importResult == {
        "status": "COMPLETE",
        "source": "sage-document-registry",
        "document": {"id": "document-1", "name": "Resume-abc.pdf", "checksum": "abc"},
    }
    assert calls[0][1] == {"sourceRoot": "downloads", "relativePath": "Resume.pdf"}


def testFormatsVerifiedResearchLinksWithoutModelRewriting():
    """Research URLs are appended deterministically and can be recalled without a new search."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherLinks", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    research = {
        "sources": [
            {"title": "Example One", "url": "https://example.com/one", "content": "one"},
            {"title": "Example Two", "url": "https://example.com/two", "content": "two"},
        ]
    }

    assert dispatcher.isSourceFollowup("Can you give me the links")
    assert dispatcher.formatResearchSources(research) == (
        "Sources:\n[1] Example One — https://example.com/one\n"
        "[2] Example Two — https://example.com/two"
    )


def testBuildsBoundedIrisImageContent(tmp_path):
    """Only validated image bytes become a local Iris multimodal request."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherVision", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    imagePath = tmp_path / "evidence.png"
    imagePath.write_bytes(b"safe-image")

    imageContent = dispatcher.buildImageContent(imagePath, "image/png")

    assert imageContent["type"] == "image_url"
    assert imageContent["image_url"]["url"].startswith("data:image/png;base64,")
    try:
        dispatcher.validateAttachmentMetadata(
            {"fileSize": 20_000_001, "mimeType": "image/png"}
        )
    except ValueError as error:
        assert "size" in str(error).lower()
    else:
        raise AssertionError("Oversized attachments must be rejected")
    try:
        dispatcher.validateAttachmentMetadata(
            {"fileSize": 10, "fileUniqueId": "../escape", "mimeType": "image/png"}
        )
    except ValueError as error:
        assert "identifier" in str(error).lower()
    else:
        raise AssertionError("Unsafe attachment identifiers must be rejected")


def testSleepRepliesWithoutCallingModel(tmp_path, monkeypatch):
    """Sleep mode keeps Telegram control responsive without loading Sage."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherSleep", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE telegram_messages (
                message_id INTEGER PRIMARY KEY, text TEXT, message_thread_id INTEGER,
                dispatch_status TEXT, reply_text TEXT, attachment_json TEXT
            )"""
        )
        connection.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO system_settings VALUES ('mode', 'SLEEP')")
        connection.execute("INSERT INTO telegram_messages VALUES (1, 'hello', 5, 'PENDING', NULL, NULL)")
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)
    sentMessages = []
    monkeypatch.setattr(dispatcher, "sendTelegramMessage", lambda secrets, text: sentMessages.append(text))

    def failModelCall(url, payload, headers):
        raise AssertionError("The model must not be called in Sleep mode")

    monkeypatch.setattr(dispatcher, "postJson", failModelCall)

    assert dispatcher.dispatchNextMessage({"SAGE_TELEGRAM_MAIN_TOPIC_ID": "5"})
    assert sentMessages == ["Sage is sleeping. Use /normal or /eco when you need me."]


def testEcoStartsAndStopsSageAroundOneMessage(tmp_path, monkeypatch):
    """Eco mode loads exactly one Sage instance for demand and unloads it afterward."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherEco", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute(
            """CREATE TABLE telegram_messages (
                message_id INTEGER PRIMARY KEY, text TEXT, message_thread_id INTEGER,
                dispatch_status TEXT, reply_text TEXT, attachment_json TEXT
            )"""
        )
        connection.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO system_settings VALUES ('mode', 'ECO')")
        connection.execute("INSERT INTO telegram_messages VALUES (1, 'hello', 5, 'PENDING', NULL, NULL)")
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)
    agentStates = []
    monkeypatch.setattr(
        dispatcher,
        "setModelAgentState",
        lambda agentName, shouldRun: agentStates.append((agentName, shouldRun)),
    )
    monkeypatch.setattr(dispatcher, "waitForSageModel", lambda secrets: None)
    monkeypatch.setattr(dispatcher, "sendTelegramMessage", lambda secrets, text: None)
    monkeypatch.setattr(
        dispatcher,
        "postJson",
        lambda url, payload, headers: {"choices": [{"message": {"content": "ready"}}]},
    )

    assert dispatcher.dispatchNextMessage(
        {"SAGE_TELEGRAM_MAIN_TOPIC_ID": "5", "SAGE_MODEL_API_KEY": "model-key"}
    )
    assert agentStates == [
        ("com.sage.model-sage", True),
        ("com.sage.model-sage", False),
    ]
