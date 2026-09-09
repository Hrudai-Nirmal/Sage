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
