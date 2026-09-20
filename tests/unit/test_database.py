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
