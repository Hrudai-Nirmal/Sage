"""Create the small SQLite foundation shared by all Sage Core repositories."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SageDatabase:
    """Own private SQLite connections and schema initialization for Sage Core."""

    def __init__(self, databasePath: Path) -> None:
        """Initialize the database at a concrete path outside the Git repository."""
        if not isinstance(databasePath, Path):
            raise TypeError("databasePath must be a pathlib.Path")

        databasePath.parent.mkdir(parents=True, exist_ok=True)
        self.databasePath = databasePath
        self._initializeSchema()

    def connectDatabase(self) -> sqlite3.Connection:
        """Open a request-scoped connection with foreign keys enforced."""
        connection = sqlite3.connect(self.databasePath)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initializeSchema(self) -> None:
        """Create schemas required for the first state and approval vertical slices."""
        with self.connectDatabase() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approved_by TEXT
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'MEDIUM',
                    due_at TEXT,
                    recurrence TEXT,
                    created_at TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id)
                );

                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    source_root TEXT NOT NULL,
                    source_relative_path TEXT NOT NULL,
                    checksum TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_runs (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    sources_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telegram_messages (
                    message_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    message_thread_id INTEGER NOT NULL,
                    sender_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telegram_callbacks (
                    callback_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_thread_id INTEGER NOT NULL,
                    sender_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    received_at TEXT NOT NULL
                );
                """
            )
            self._addTaskColumnIfMissing(connection, "priority", "TEXT NOT NULL DEFAULT 'MEDIUM'")
            self._addTaskColumnIfMissing(connection, "due_at", "TEXT")
            self._addTaskColumnIfMissing(connection, "recurrence", "TEXT")
            self._addTelegramColumnIfMissing(connection, "dispatch_status", "TEXT NOT NULL DEFAULT 'PENDING'")
            self._addTelegramColumnIfMissing(connection, "reply_text", "TEXT")

    def _addTaskColumnIfMissing(
        self, connection: sqlite3.Connection, columnName: str, columnDefinition: str
    ) -> None:
        """Migrate early local databases without discarding approved task history."""
        taskColumns = {
            str(columnRow[1])
            for columnRow in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if columnName not in taskColumns:
            connection.execute(f"ALTER TABLE tasks ADD COLUMN {columnName} {columnDefinition}")

    def _addTelegramColumnIfMissing(
        self, connection: sqlite3.Connection, columnName: str, columnDefinition: str
    ) -> None:
        """Add dispatcher state without discarding previously received Telegram messages."""
        messageColumns = {
            str(columnRow[1])
            for columnRow in connection.execute("PRAGMA table_info(telegram_messages)").fetchall()
        }
        if columnName not in messageColumns:
            connection.execute(f"ALTER TABLE telegram_messages ADD COLUMN {columnName} {columnDefinition}")
