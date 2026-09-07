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
