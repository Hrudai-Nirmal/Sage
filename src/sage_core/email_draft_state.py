"""Own immutable Gmail draft snapshots and their approval-bound lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import sqlite3
from uuid import uuid4

from sage_core.database import SageDatabase


class EmailDraftStateRepository:
    """Persist versioned email content while keeping approval state explicit."""

    def __init__(self, database: SageDatabase) -> None:
        """Bind draft state to Sage's authoritative local database."""
        self.database = database

    def createApprovalSnapshot(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, object],
        approvalRequestId: str,
    ) -> dict[str, object]:
        """Create or bind the exact immutable version represented by an approval card."""
        draftId = payload.get("draftId")
        draftVersion = payload.get("draftVersion")
        if draftId is None and draftVersion is None:
            draftId = str(uuid4())
            draftVersion = 1
            self._insertDraft(
                connection,
                str(draftId),
                int(draftVersion),
                payload,
                "PENDING_APPROVAL",
                approvalRequestId,
                None,
            )
        elif isinstance(draftId, str) and isinstance(draftVersion, int):
            draftRow = self._getDraftRow(connection, draftId, draftVersion)
            if draftRow is None or str(draftRow[6]) != "DRAFT":
                raise ValueError("Email draft version is not available for approval")
            currentVersion = connection.execute(
                "SELECT MAX(version) FROM email_drafts WHERE draft_id = ?",
                (draftId,),
            ).fetchone()[0]
            if int(currentVersion) != draftVersion or not self._matchesPayload(draftRow, payload):
                raise ValueError("Email approval does not match the current draft version")
            connection.execute(
                """UPDATE email_drafts
                   SET status = 'PENDING_APPROVAL', approval_request_id = ?
                   WHERE draft_id = ? AND version = ? AND status = 'DRAFT'""",
                (approvalRequestId, draftId, draftVersion),
            )
        else:
            raise ValueError("Email draft ID and version must be supplied together")
        return {**payload, "draftId": str(draftId), "draftVersion": int(draftVersion)}

    def createDraft(
        self, payload: dict[str, object], idempotencyKey: str | None = None
    ) -> dict[str, object]:
        """Create the first immutable version without requesting permission to send."""
        draftId = str(uuid4())
        with self.database.connectDatabase() as connection:
            existingDraft = self._getDraftByIdempotencyKey(connection, idempotencyKey)
            if existingDraft is not None:
                return self._serializeDraft(existingDraft)
            self._insertDraft(
                connection, draftId, 1, payload, "DRAFT", None, idempotencyKey
            )
        return self.getDraft(draftId, 1)

    def reviseDraft(
        self,
        draftId: str,
        expectedVersion: int,
        payload: dict[str, object],
        idempotencyKey: str | None = None,
    ) -> dict[str, object]:
        """Append one version and invalidate the previous version's pending approval."""
        if not isinstance(draftId, str) or not draftId.strip():
            raise ValueError("Email draft ID is required")
        if not isinstance(expectedVersion, int) or expectedVersion < 1:
            raise ValueError("Expected email draft version must be positive")
        with self.database.connectDatabase() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existingDraft = self._getDraftByIdempotencyKey(connection, idempotencyKey)
            if existingDraft is not None:
                return self._serializeDraft(existingDraft)
            currentRow = connection.execute(
                """SELECT draft_id, version, account_key, recipients_json, subject, body,
                          status, approval_request_id
                   FROM email_drafts WHERE draft_id = ? ORDER BY version DESC LIMIT 1""",
                (draftId.strip(),),
            ).fetchone()
            if currentRow is None:
                raise LookupError("Email draft was not found")
            if int(currentRow[1]) != expectedVersion:
                raise ValueError("Email draft has a newer version")
            if str(currentRow[6]) not in {"DRAFT", "PENDING_APPROVAL"}:
                raise ValueError("Email draft can no longer be revised")
            approvalRequestId = currentRow[7]
            if approvalRequestId:
                connection.execute(
                    """UPDATE approval_requests SET status = 'SUPERSEDED'
                       WHERE id = ? AND status = 'PENDING'""",
                    (str(approvalRequestId),),
                )
            connection.execute(
                """UPDATE email_drafts SET status = 'SUPERSEDED'
                   WHERE draft_id = ? AND version = ?""",
                (draftId.strip(), expectedVersion),
            )
            nextVersion = expectedVersion + 1
            self._insertDraft(
                connection,
                draftId.strip(),
                nextVersion,
                payload,
                "DRAFT",
                None,
                idempotencyKey,
            )
        return self.getDraft(draftId.strip(), nextVersion)

    def getDraft(self, draftId: str, version: int) -> dict[str, object]:
        """Return one exact draft version without mutable outbox details."""
        with self.database.connectDatabase() as connection:
            draftRow = self._getDraftRow(connection, draftId, version)
        if draftRow is None:
            raise LookupError("Email draft version was not found")
        return self._serializeDraft(draftRow)

    def listDrafts(self, limit: int = 20) -> list[dict[str, object]]:
        """Return the most recent bounded draft versions for operator inspection."""
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Email draft limit must be between 1 and 100")
        with self.database.connectDatabase() as connection:
            draftRows = connection.execute(
                """SELECT draft_id, version, account_key, recipients_json, subject, body,
                          status, approval_request_id
                   FROM email_drafts ORDER BY created_at DESC, version DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._serializeDraft(draftRow) for draftRow in draftRows]

    def markApproved(
        self, connection: sqlite3.Connection, draftId: str, version: int, approvalRequestId: str
    ) -> None:
        """Transition only the exact version bound to the independently approved card."""
        updateResult = connection.execute(
            """UPDATE email_drafts SET status = 'APPROVED'
               WHERE draft_id = ? AND version = ? AND status = 'PENDING_APPROVAL'
                 AND approval_request_id = ?""",
            (draftId, version, approvalRequestId),
        )
        if updateResult.rowcount != 1:
            raise ValueError("Approved email draft version is no longer current")

    def markCancelled(
        self, connection: sqlite3.Connection, approvalRequestId: str
    ) -> None:
        """Close the exact pending draft version attached to a declined approval."""
        connection.execute(
            """UPDATE email_drafts SET status = 'CANCELLED'
               WHERE approval_request_id = ? AND status = 'PENDING_APPROVAL'""",
            (approvalRequestId,),
        )

    def _insertDraft(
        self,
        connection: sqlite3.Connection,
        draftId: str,
        version: int,
        payload: dict[str, object],
        draftStatus: str,
        approvalRequestId: str | None,
        idempotencyKey: str | None,
    ) -> None:
        """Insert content once so later lifecycle changes cannot rewrite it."""
        accountKey = payload.get("accountKey")
        recipients = payload.get("to")
        subject = payload.get("subject")
        body = payload.get("body")
        if accountKey not in {"personal-work", "work", "personal", "college"}:
            raise ValueError("Email draft account is not configured")
        if not isinstance(recipients, list) or not recipients:
            raise ValueError("Email draft requires recipients")
        if not isinstance(subject, str) or not isinstance(body, str) or not body:
            raise ValueError("Email draft requires complete content")
        connection.execute(
            """INSERT INTO email_drafts (
                   draft_id, version, account_key, recipients_json, subject, body,
                   status, created_at, approval_request_id, idempotency_key
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                draftId,
                version,
                accountKey,
                json.dumps(recipients),
                subject,
                body,
                draftStatus,
                datetime.now(UTC).isoformat(),
                approvalRequestId,
                idempotencyKey,
            ),
        )

    def _getDraftByIdempotencyKey(
        self, connection: sqlite3.Connection, idempotencyKey: str | None
    ) -> sqlite3.Row | tuple[object, ...] | None:
        """Resolve a previously committed dispatcher request before mutating versions."""
        if not isinstance(idempotencyKey, str) or not idempotencyKey.strip():
            return None
        return connection.execute(
            """SELECT draft_id, version, account_key, recipients_json, subject, body,
                      status, approval_request_id
               FROM email_drafts WHERE idempotency_key = ?""",
            (idempotencyKey.strip(),),
        ).fetchone()

    def _getDraftRow(
        self, connection: sqlite3.Connection, draftId: str, version: int
    ) -> sqlite3.Row | tuple[object, ...] | None:
        """Load a full immutable snapshot by its composite identity."""
        return connection.execute(
            """SELECT draft_id, version, account_key, recipients_json, subject, body,
                      status, approval_request_id
               FROM email_drafts WHERE draft_id = ? AND version = ?""",
            (draftId, version),
        ).fetchone()

    def _matchesPayload(
        self, draftRow: sqlite3.Row | tuple[object, ...], payload: dict[str, object]
    ) -> bool:
        """Prevent an approval reference from smuggling content different from its snapshot."""
        return (
            str(draftRow[2]) == payload.get("accountKey")
            and json.loads(str(draftRow[3])) == payload.get("to")
            and str(draftRow[4]) == payload.get("subject")
            and str(draftRow[5]) == payload.get("body")
        )

    def _serializeDraft(
        self, draftRow: sqlite3.Row | tuple[object, ...]
    ) -> dict[str, object]:
        """Map an internal SQLite row to the stable draft contract."""
        return {
            "id": str(draftRow[0]),
            "version": int(draftRow[1]),
            "accountKey": str(draftRow[2]),
            "to": json.loads(str(draftRow[3])),
            "subject": str(draftRow[4]),
            "body": str(draftRow[5]),
            "status": str(draftRow[6]),
            "approvalRequestId": str(draftRow[7]) if draftRow[7] else None,
        }
