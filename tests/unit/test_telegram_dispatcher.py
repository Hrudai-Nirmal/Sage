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


def testRecognizesExplicitResearchCommand():
    """Online research is deliberate and never inferred from ordinary conversation."""
    dispatcherPath = Path(__file__).parents[2] / "scripts" / "run-telegram-dispatcher.py"
    moduleSpec = spec_from_file_location("sageTelegramDispatcherResearch", dispatcherPath)
    assert moduleSpec is not None and moduleSpec.loader is not None
    dispatcher = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(dispatcher)

    assert dispatcher.getResearchQuery("/research current MLX releases") == "current MLX releases"
    assert dispatcher.getResearchQuery("what is new?") is None
    assert dispatcher.getResearchQuery("/research   ") is None


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
                dispatch_status TEXT, reply_text TEXT
            )"""
        )
        connection.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO system_settings VALUES ('mode', 'SLEEP')")
        connection.execute("INSERT INTO telegram_messages VALUES (1, 'hello', 5, 'PENDING', NULL)")
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
                dispatch_status TEXT, reply_text TEXT
            )"""
        )
        connection.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO system_settings VALUES ('mode', 'ECO')")
        connection.execute("INSERT INTO telegram_messages VALUES (1, 'hello', 5, 'PENDING', NULL)")
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
