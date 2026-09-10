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

                CREATE TABLE IF NOT EXISTS email_messages (
                    account_key TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipients_json TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    body_text TEXT NOT NULL,
                    label_ids_json TEXT NOT NULL,
                    internal_date TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    PRIMARY KEY (account_key, message_id)
                );

                CREATE TABLE IF NOT EXISTS calendar_events (
                    account_key TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    html_link TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    attendees_json TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    PRIMARY KEY (account_key, event_id)
                );

                CREATE TABLE IF NOT EXISTS drive_files (
                    account_key TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    web_view_link TEXT NOT NULL,
                    parents_json TEXT NOT NULL,
                    owners_json TEXT NOT NULL,
                    size TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    PRIMARY KEY (account_key, file_id)
                );

                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    recurrence TEXT,
                    next_run_at TEXT,
                    created_at TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS scheduled_deliveries (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    error_type TEXT,
                    completed_at TEXT,
                    UNIQUE(schedule_id, due_at),
                    FOREIGN KEY (schedule_id) REFERENCES schedules(id)
                );

                CREATE TABLE IF NOT EXISTS telegram_messages (
                    message_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    message_thread_id INTEGER NOT NULL,
                    sender_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    attachment_json TEXT,
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
            self._addTelegramColumnIfMissing(connection, "attachment_json", "TEXT")

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
