"""Create the small SQLite foundation shared by all Sage Core repositories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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

    @contextmanager
    def connectDatabase(self) -> Iterator[sqlite3.Connection]:
        """Yield a request-scoped connection and always release its descriptor."""
        connection = sqlite3.connect(self.databasePath)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
                    approved_by TEXT,
                    idempotency_key TEXT
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

                CREATE TABLE IF NOT EXISTS case_notes (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    note_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(id)
                );

                CREATE TABLE IF NOT EXISTS case_milestones (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    due_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(id)
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

                CREATE TABLE IF NOT EXISTS context_records (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approval_request_id TEXT,
                    UNIQUE(category, record_key),
                    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id)
                );

                CREATE TABLE IF NOT EXISTS context_revisions (
                    id TEXT PRIMARY KEY,
                    context_record_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    value TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    approval_request_id TEXT,
                    idempotency_key TEXT,
                    UNIQUE(context_record_id, version),
                    FOREIGN KEY (context_record_id) REFERENCES context_records(id),
                    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id)
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

                CREATE TABLE IF NOT EXISTS calendar_reminders (
                    account_key TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_updated_at TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    error_type TEXT,
                    completed_at TEXT,
                    PRIMARY KEY (account_key, event_id),
                    FOREIGN KEY (account_key, event_id)
                        REFERENCES calendar_events(account_key, event_id)
                );

                CREATE TABLE IF NOT EXISTS email_triage_jobs (
                    account_key TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    error_type TEXT,
                    completed_at TEXT,
                    classification_json TEXT,
                    PRIMARY KEY (account_key, message_id),
                    FOREIGN KEY (account_key, message_id)
                        REFERENCES email_messages(account_key, message_id)
                );

                CREATE TABLE IF NOT EXISTS drive_actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    account_key TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    error_type TEXT,
                    completed_at TEXT,
                    approval_request_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id)
                );

                CREATE TABLE IF NOT EXISTS google_actions (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    action_type TEXT NOT NULL,
                    account_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    error_type TEXT,
                    remote_id TEXT,
                    completed_at TEXT,
                    approval_request_id TEXT UNIQUE,
                    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id)
                );

                CREATE TABLE IF NOT EXISTS email_drafts (
                    draft_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    account_key TEXT NOT NULL,
                    recipients_json TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approval_request_id TEXT UNIQUE,
                    idempotency_key TEXT,
                    PRIMARY KEY (draft_id, version)
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

                CREATE TABLE IF NOT EXISTS observer_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observer_sources (
                    id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    browser_family TEXT,
                    profile_id TEXT NOT NULL,
                    profile_label TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(source_kind, browser_family, profile_id)
                );

                CREATE TABLE IF NOT EXISTS observer_sessions (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    last_event_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    activity_category TEXT,
                    summary TEXT,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    analysis_status TEXT NOT NULL DEFAULT 'PENDING',
                    analysis_attempts INTEGER NOT NULL DEFAULT 0,
                    analysis_claimed_at TEXT,
                    next_attempt_at TEXT,
                    error_type TEXT,
                    FOREIGN KEY (source_id) REFERENCES observer_sources(id)
                );

                CREATE TABLE IF NOT EXISTS observer_events (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    url TEXT,
                    domain TEXT,
                    title TEXT,
                    page_text TEXT,
                    search_query TEXT,
                    active_duration_seconds INTEGER,
                    video_json TEXT,
                    content_hash TEXT NOT NULL,
                    processing_status TEXT NOT NULL,
                    raw_expires_at TEXT NOT NULL,
                    extract_expires_at TEXT,
                    FOREIGN KEY (source_id) REFERENCES observer_sources(id),
                    FOREIGN KEY (session_id) REFERENCES observer_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS observer_memories (
                    id TEXT PRIMARY KEY,
                    memory_kind TEXT NOT NULL,
                    trust_level TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning_summary TEXT NOT NULL,
                    evidence_count INTEGER NOT NULL,
                    independent_session_count INTEGER NOT NULL,
                    is_uncertain INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(memory_kind, trust_level, subject_key)
                );

                CREATE TABLE IF NOT EXISTS observer_memory_evidence (
                    memory_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    evidence_excerpt TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (memory_id, event_id),
                    FOREIGN KEY (memory_id) REFERENCES observer_memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (event_id) REFERENCES observer_events(id),
                    FOREIGN KEY (session_id) REFERENCES observer_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS observer_memory_candidates (
                    id TEXT PRIMARY KEY,
                    memory_kind TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning_summary TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    evidence_event_ids_json TEXT NOT NULL,
                    is_uncertain INTEGER NOT NULL DEFAULT 0,
                    observed_at TEXT NOT NULL,
                    UNIQUE(memory_kind, subject_key, session_id),
                    FOREIGN KEY (session_id) REFERENCES observer_sessions(id)
                );
                """
            )
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS observer_memory_fts
                   USING fts5(memory_id UNINDEXED, subject_key, summary)"""
            )
            self._addTaskColumnIfMissing(connection, "priority", "TEXT NOT NULL DEFAULT 'MEDIUM'")
            self._addTaskColumnIfMissing(connection, "due_at", "TEXT")
            self._addTaskColumnIfMissing(connection, "recurrence", "TEXT")
            self._addColumnIfMissing(connection, "tasks", "updated_at", "TEXT")
            self._addColumnIfMissing(connection, "cases", "updated_at", "TEXT")
            self._addColumnIfMissing(connection, "schedules", "updated_at", "TEXT")
            self._addTelegramColumnIfMissing(connection, "dispatch_status", "TEXT NOT NULL DEFAULT 'PENDING'")
            self._addTelegramColumnIfMissing(connection, "reply_text", "TEXT")
            self._addTelegramColumnIfMissing(connection, "attachment_json", "TEXT")
            self._addApprovalColumnIfMissing(connection, "idempotency_key", "TEXT")
            self._addEmailDraftColumnIfMissing(connection, "idempotency_key", "TEXT")
            self._addContextRevisionColumnIfMissing(connection, "idempotency_key", "TEXT")
            self._addObserverSessionColumnIfMissing(
                connection, "analysis_status", "TEXT NOT NULL DEFAULT 'PENDING'"
            )
            self._addObserverSessionColumnIfMissing(
                connection, "analysis_attempts", "INTEGER NOT NULL DEFAULT 0"
            )
            self._addObserverSessionColumnIfMissing(connection, "analysis_claimed_at", "TEXT")
            self._addObserverSessionColumnIfMissing(connection, "next_attempt_at", "TEXT")
            self._addObserverSessionColumnIfMissing(connection, "error_type", "TEXT")
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS approval_requests_idempotency_key
                   ON approval_requests(idempotency_key) WHERE idempotency_key IS NOT NULL"""
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS email_drafts_idempotency_key
                   ON email_drafts(idempotency_key) WHERE idempotency_key IS NOT NULL"""
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS context_revisions_idempotency_key
                   ON context_revisions(idempotency_key) WHERE idempotency_key IS NOT NULL"""
            )

    def _addColumnIfMissing(
        self,
        connection: sqlite3.Connection,
        tableName: str,
        columnName: str,
        columnDefinition: str,
    ) -> None:
        """Apply one additive migration to a fixed internal table identifier."""
        supportedTables = {"cases", "schedules", "tasks"}
        if tableName not in supportedTables:
            raise ValueError("Unsupported migration table")
        existingColumns = {
            str(columnRow[1])
            for columnRow in connection.execute(f"PRAGMA table_info({tableName})").fetchall()
        }
        if columnName not in existingColumns:
            connection.execute(
                f"ALTER TABLE {tableName} ADD COLUMN {columnName} {columnDefinition}"
            )

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

    def _addApprovalColumnIfMissing(
        self, connection: sqlite3.Connection, columnName: str, columnDefinition: str
    ) -> None:
        """Add proposal deduplication without discarding previous approval history."""
        approvalColumns = {
            str(columnRow[1])
            for columnRow in connection.execute("PRAGMA table_info(approval_requests)").fetchall()
        }
        if columnName not in approvalColumns:
            connection.execute(
                f"ALTER TABLE approval_requests ADD COLUMN {columnName} {columnDefinition}"
            )

    def _addEmailDraftColumnIfMissing(
        self, connection: sqlite3.Connection, columnName: str, columnDefinition: str
    ) -> None:
        """Add replay protection without discarding previously saved draft history."""
        draftColumns = {
            str(columnRow[1])
            for columnRow in connection.execute("PRAGMA table_info(email_drafts)").fetchall()
        }
        if columnName not in draftColumns:
            connection.execute(
                f"ALTER TABLE email_drafts ADD COLUMN {columnName} {columnDefinition}"
            )

    def _addContextRevisionColumnIfMissing(
        self, connection: sqlite3.Connection, columnName: str, columnDefinition: str
    ) -> None:
        """Add context replay protection without discarding personal revision history."""
        revisionColumns = {
            str(columnRow[1])
            for columnRow in connection.execute(
                "PRAGMA table_info(context_revisions)"
            ).fetchall()
        }
        if columnName not in revisionColumns:
            connection.execute(
                f"ALTER TABLE context_revisions ADD COLUMN {columnName} {columnDefinition}"
            )

    def _addObserverSessionColumnIfMissing(
        self, connection: sqlite3.Connection, columnName: str, columnDefinition: str
    ) -> None:
        """Add retry state without discarding activity sessions collected before upgrades."""
        sessionColumns = {
            str(columnRow[1])
            for columnRow in connection.execute(
                "PRAGMA table_info(observer_sessions)"
            ).fetchall()
        }
        if columnName not in sessionColumns:
            connection.execute(
                f"ALTER TABLE observer_sessions ADD COLUMN {columnName} {columnDefinition}"
            )
