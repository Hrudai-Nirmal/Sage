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
                """
            )
