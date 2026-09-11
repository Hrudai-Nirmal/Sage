"""Unit tests for Sage's native Telegram dispatcher failure boundaries."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3
from urllib.error import HTTPError


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
            "CREATE TABLE calendar_events (summary TEXT, description TEXT, location TEXT, start_at TEXT, end_at TEXT)"
        )
        connection.execute(
            "INSERT INTO calendar_events VALUES ('Placement interview', 'Technical round', 'Room 201', '2026-09-12T10:00:00+05:30', '2026-09-12T11:00:00+05:30')"
        )
    monkeypatch.setattr(dispatcher, "DATABASE_PATH", databasePath)

    assert dispatcher.getLocalSearchCommand("/calendar placement") == ("calendar", "placement")
    assert dispatcher.getLocalSearchCommand("/drive handbook") is None
    assert "Placement interview" in dispatcher.formatCalendarSearch(dispatcher.searchIndexedCalendar("placement"))


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
