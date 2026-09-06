"""Persist the operator-selected Sage runtime mode outside orchestration state."""

from __future__ import annotations

from sage_core.database import SageDatabase


DEFAULT_MODE = "NORMAL"


class SystemStateRepository:
    """Provide the small, durable interface for Sage's operational mode."""

    def __init__(self, database: SageDatabase) -> None:
        """Prepare the SQLite schema at the supplied private runtime path."""
        self.database = database

    def getMode(self) -> str:
        """Return the saved mode, creating the safe normal default when absent."""
        with self.database.connectDatabase() as connection:
            row = connection.execute(
                "SELECT value FROM system_settings WHERE key = 'mode'"
            ).fetchone()
            if row is not None:
                return str(row[0])

            connection.execute(
                "INSERT INTO system_settings (key, value) VALUES ('mode', ?)",
                (DEFAULT_MODE,),
            )
            return DEFAULT_MODE

    def setMode(self, mode: str) -> str:
        """Persist one validated operator-selected mode for all service controllers."""
        with self.database.connectDatabase() as connection:
            connection.execute(
                """
                INSERT INTO system_settings (key, value) VALUES ('mode', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (mode,),
            )

        return mode
