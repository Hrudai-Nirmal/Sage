"""Test the shared SQLite connection lifecycle."""

import sqlite3

import pytest

from sage_core.database import SageDatabase


def testConnectDatabaseClosesConnectionAfterContext(tmp_path):
    """Every repository block must release its file descriptor immediately."""
    database = SageDatabase(tmp_path / "sage.db")

    with database.connectDatabase() as connection:
        connection.execute("SELECT 1").fetchone()

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def testDatabaseMigratesDesktopIdentityOntoExistingObserverEvents(tmp_path):
    """Native app provenance must be added without discarding previously collected events."""
    databasePath = tmp_path / "sage.db"
    with sqlite3.connect(databasePath) as connection:
        connection.execute("CREATE TABLE observer_events (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO observer_events (id) VALUES ('existing-event')")

    database = SageDatabase(databasePath)

    with database.connectDatabase() as connection:
        columnNames = {
            str(columnRow[1])
            for columnRow in connection.execute(
                "PRAGMA table_info(observer_events)"
            ).fetchall()
        }
        existingEvent = connection.execute(
            "SELECT id FROM observer_events WHERE id = 'existing-event'"
        ).fetchone()
    assert {"app_bundle_id", "app_name"}.issubset(columnNames)
    assert existingEvent == ("existing-event",)
