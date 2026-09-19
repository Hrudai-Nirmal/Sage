"""Maintain Sage's confirmed personal context with provenance and revision history."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


STANDARD_CONTEXT_CATEGORIES = frozenset(
    {"preferences", "projects-commitments", "user-rules"}
)
SENSITIVE_CONTEXT_CATEGORIES = frozenset(
    {"education-work", "identity", "important-dates", "owned-items", "people"}
)
CONTEXT_CATEGORIES = STANDARD_CONTEXT_CATEGORIES | SENSITIVE_CONTEXT_CATEGORIES
CONTEXT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")


class ContextStateRepository:
    """Own confirmed personal context while keeping model suggestions non-authoritative."""

    def __init__(self, database: SageDatabase, dataRoot: Path) -> None:
        """Bind the registry to one database and its managed context directory."""
        if not isinstance(dataRoot, Path):
            raise TypeError("dataRoot must be a pathlib.Path")
        self.database = database
        self.contextRoot = dataRoot / "context"
        self.contextRoot.mkdir(parents=True, exist_ok=True)
        self.contextRoot.chmod(0o700)
        self.auditStateRepository = AuditStateRepository(database)
        with self.database.connectDatabase() as connection:
            self._refreshMarkdownMirrors(connection)

    def upsertRecord(
        self,
        category: str,
        recordKey: str,
        value: str,
        sourceType: str,
        sourceRef: str,
        actor: str,
        hasSensitiveApproval: bool = False,
        expectedVersion: int | None = None,
        idempotencyKey: str | None = None,
        approvalRequestId: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        """Create or revise one confirmed record after enforcing category authority."""
        normalizedCategory, normalizedKey, normalizedValue = self._validateRecord(
            category, recordKey, value
        )
        if (
            normalizedCategory in SENSITIVE_CONTEXT_CATEGORIES
            and not hasSensitiveApproval
        ):
            raise PermissionError("Sensitive context requires independent approval")
        normalizedSourceType = self._validateText(sourceType, "sourceType", 100)
        normalizedSourceRef = self._validateText(sourceRef, "sourceRef", 500)
        normalizedActor = self._validateText(actor, "actor", 200)
        normalizedIdempotencyKey = (
            self._validateText(idempotencyKey, "idempotencyKey", 500)
            if idempotencyKey is not None
            else None
        )
        if connection is not None:
            record = self._upsertRecord(
                connection,
                normalizedCategory,
                normalizedKey,
                normalizedValue,
                normalizedSourceType,
                normalizedSourceRef,
                normalizedActor,
                expectedVersion,
                normalizedIdempotencyKey,
                approvalRequestId,
            )
            isReplay = bool(record.pop("_isReplay", False))
            if not isReplay:
                self._refreshMarkdownMirrors(connection)
        else:
            with self.database.connectDatabase() as ownedConnection:
                record = self._upsertRecord(
                    ownedConnection,
                    normalizedCategory,
                    normalizedKey,
                    normalizedValue,
                    normalizedSourceType,
                    normalizedSourceRef,
                    normalizedActor,
                    expectedVersion,
                    normalizedIdempotencyKey,
                    approvalRequestId,
                )
                isReplay = bool(record.pop("_isReplay", False))
                if not isReplay:
                    self._refreshMarkdownMirrors(ownedConnection)
        return record

    def forgetRecord(
        self,
        recordId: str,
        actor: str,
        hasApproval: bool = False,
        expectedVersion: int | None = None,
        approvalRequestId: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        """Redact one record and all historical values after independent approval."""
        if not hasApproval:
            raise PermissionError("Forgetting context requires independent approval")
        normalizedRecordId = self._validateText(recordId, "recordId", 100)
        normalizedActor = self._validateText(actor, "actor", 200)
        if connection is not None:
            forgottenRecord = self._forgetRecord(
                connection,
                normalizedRecordId,
                normalizedActor,
                expectedVersion,
                approvalRequestId,
            )
            self._refreshMarkdownMirrors(connection)
        else:
            with self.database.connectDatabase() as ownedConnection:
                forgottenRecord = self._forgetRecord(
                    ownedConnection,
                    normalizedRecordId,
                    normalizedActor,
                    expectedVersion,
                    approvalRequestId,
                )
                self._refreshMarkdownMirrors(ownedConnection)
        return forgottenRecord

    def upsertApprovedRecords(
        self,
        records: list[dict[str, object]],
        actor: str,
        approvalRequestId: str,
        connection: sqlite3.Connection,
    ) -> list[dict[str, object]]:
        """Apply a reviewed sensitive batch atomically and refresh views once."""
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError("Sensitive context batch must contain 1 to 100 records")
        normalizedActor = self._validateText(actor, "actor", 200)
        normalizedApprovalId = self._validateText(
            approvalRequestId, "approvalRequestId", 100
        )
        normalizedRecords: list[tuple[str, str, str, str, str, int]] = []
        seenTargets: set[tuple[str, str]] = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Every sensitive context batch item must be a record")
            category, recordKey, value = self._validateRecord(
                record.get("category"), record.get("recordKey"), record.get("value")
            )
            if category not in SENSITIVE_CONTEXT_CATEGORIES:
                raise ValueError("Sensitive context batches cannot contain ordinary records")
            target = (category, recordKey)
            if target in seenTargets:
                raise ValueError("Sensitive context batch contains a duplicate target")
            seenTargets.add(target)
            sourceType = self._validateText(
                record.get("sourceType"), "sourceType", 100
            )
            sourceRef = self._validateText(record.get("sourceRef"), "sourceRef", 500)
            expectedVersion = record.get("expectedVersion")
            if isinstance(expectedVersion, bool) or not isinstance(expectedVersion, int):
                raise ValueError("expectedVersion must be a non-negative integer")
            if expectedVersion < 0:
                raise ValueError("expectedVersion must be a non-negative integer")
            normalizedRecords.append(
                (category, recordKey, value, sourceType, sourceRef, expectedVersion)
            )

        storedRecords = [
            self._upsertRecord(
                connection,
                category,
                recordKey,
                value,
                sourceType,
                sourceRef,
                normalizedActor,
                expectedVersion,
                None,
                normalizedApprovalId,
            )
            for category, recordKey, value, sourceType, sourceRef, expectedVersion in (
                normalizedRecords
            )
        ]
        self._refreshMarkdownMirrors(connection)
        return storedRecords

    def searchRecords(self, query: str = "", resultLimit: int = 20) -> list[dict[str, object]]:
        """Search active confirmed records without returning forgotten values."""
        if not isinstance(query, str) or len(query) > 2_000:
            raise ValueError("Context query must be a string of at most 2000 characters")
        if resultLimit < 1 or resultLimit > 100:
            raise ValueError("Context result limit must be between 1 and 100")
        queryTerms = [term.casefold() for term in re.findall(r"[\w.-]+", query)[:20]]
        whereClauses = ["status = 'ACTIVE'"]
        queryValues: list[object] = []
        searchableColumns = "lower(category || ' ' || record_key || ' ' || value)"
        for queryTerm in queryTerms:
            whereClauses.append(f"{searchableColumns} LIKE ?")
            queryValues.append(f"%{queryTerm}%")
        queryValues.append(resultLimit)
        with self.database.connectDatabase() as connection:
            recordRows = connection.execute(
                f"""SELECT id, category, record_key, value, sensitivity, version,
                           source_type, source_ref, updated_at
                    FROM context_records
                    WHERE {' AND '.join(whereClauses)}
                    ORDER BY category, record_key LIMIT ?""",
                queryValues,
            ).fetchall()
        return [self._serializeRecord(recordRow) for recordRow in recordRows]

    def getRecord(self, recordId: str) -> dict[str, object]:
        """Return one active record by exact identifier for correction or deletion."""
        normalizedRecordId = self._validateText(recordId, "recordId", 100)
        with self.database.connectDatabase() as connection:
            recordRow = connection.execute(
                """SELECT id, category, record_key, value, sensitivity, version,
                          source_type, source_ref, updated_at
                   FROM context_records WHERE id = ? AND status = 'ACTIVE'""",
                (normalizedRecordId,),
            ).fetchone()
        if recordRow is None:
            raise LookupError("Context record was not found")
        return self._serializeRecord(recordRow)

    def listRevisions(self, recordId: str) -> list[dict[str, object]]:
        """Return the bounded provenance trail for one record in version order."""
        normalizedRecordId = self._validateText(recordId, "recordId", 100)
        with self.database.connectDatabase() as connection:
            revisionRows = connection.execute(
                """SELECT version, value, source_type, source_ref, actor, changed_at
                   FROM context_revisions WHERE context_record_id = ?
                   ORDER BY version LIMIT 100""",
                (normalizedRecordId,),
            ).fetchall()
        return [
            {
                "actor": str(actor),
                "changedAt": str(changedAt),
                "sourceRef": str(sourceRef),
                "sourceType": str(sourceType),
                "value": str(value),
                "version": int(version),
            }
            for version, value, sourceType, sourceRef, actor, changedAt in revisionRows
        ]

    def getRelevantContextPrompt(self, query: str, resultLimit: int = 12) -> str:
        """Render global rules and query-relevant confirmed records for one model turn."""
        if not isinstance(query, str) or len(query) > 20_000:
            raise ValueError("Context relevance query is invalid")
        allRecords = self.searchRecords("", 100)
        queryTerms = {
            term.casefold()
            for term in re.findall(r"[A-Za-z0-9._-]{3,}", query)
            if term.casefold() not in {"what", "when", "where", "which", "with", "from", "that", "this", "have", "about"}
        }
        relevantRecords = []
        for record in allRecords:
            searchableText = f"{record['key']} {record['value']}".casefold()
            if record["category"] in {"identity", "preferences", "user-rules"} or any(
                queryTerm in searchableText for queryTerm in queryTerms
            ):
                relevantRecords.append(record)
            if len(relevantRecords) >= resultLimit:
                break
        if not relevantRecords:
            return (
                "## Confirmed personal context\n"
                "No confirmed context is relevant to this turn. Do not infer missing facts."
            )
        contextLines = [
            f"- [{record['category']}] {record['key']}: {str(record['value'])[:600]}"
            for record in relevantRecords
        ]
        return (
            "## Confirmed personal context\n"
            "Use only these confirmed records. Do not infer missing facts or treat conversation guesses as memory.\n"
            + "\n".join(contextLines)
        )[:6_000]

    def _upsertRecord(
        self,
        connection: sqlite3.Connection,
        category: str,
        recordKey: str,
        value: str,
        sourceType: str,
        sourceRef: str,
        actor: str,
        expectedVersion: int | None,
        idempotencyKey: str | None,
        approvalRequestId: str | None,
    ) -> dict[str, object]:
        """Apply one validated revision inside the caller's transaction."""
        if idempotencyKey is not None:
            replayRow = connection.execute(
                """SELECT records.id, records.category, records.record_key,
                          revisions.value, records.sensitivity, revisions.version,
                          revisions.source_type, revisions.source_ref, revisions.changed_at
                   FROM context_revisions AS revisions
                   JOIN context_records AS records
                     ON records.id = revisions.context_record_id
                   WHERE revisions.idempotency_key = ?""",
                (idempotencyKey,),
            ).fetchone()
            if replayRow is not None:
                replayRecord = self._serializeRecord(replayRow)
                if (
                    replayRecord["category"] != category
                    or replayRecord["key"] != recordKey
                    or replayRecord["value"] != value
                    or replayRecord["sourceType"] != sourceType
                    or replayRecord["sourceRef"] != sourceRef
                ):
                    raise ValueError("Context idempotency key was reused with different content")
                replayRecord["_isReplay"] = True
                return replayRecord
        existingRow = connection.execute(
            """SELECT id, version, created_at FROM context_records
               WHERE category = ? AND record_key = ?""",
            (category, recordKey),
        ).fetchone()
        currentVersion = int(existingRow[1]) if existingRow else 0
        if expectedVersion is not None and expectedVersion != currentVersion:
            raise ValueError("Context record version changed before approval")
        changedAt = datetime.now(UTC).isoformat()
        recordId = str(existingRow[0]) if existingRow else str(uuid4())
        version = currentVersion + 1
        createdAt = str(existingRow[2]) if existingRow else changedAt
        sensitivity = (
            "SENSITIVE" if category in SENSITIVE_CONTEXT_CATEGORIES else "STANDARD"
        )
        connection.execute(
            """INSERT INTO context_records (
                   id, category, record_key, value, sensitivity, status, source_type,
                   source_ref, version, created_at, updated_at, approval_request_id
               ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?)
               ON CONFLICT(category, record_key) DO UPDATE SET
                   value = excluded.value,
                   sensitivity = excluded.sensitivity,
                   status = 'ACTIVE',
                   source_type = excluded.source_type,
                   source_ref = excluded.source_ref,
                   version = excluded.version,
                   updated_at = excluded.updated_at,
                   approval_request_id = excluded.approval_request_id""",
            (
                recordId,
                category,
                recordKey,
                value,
                sensitivity,
                sourceType,
                sourceRef,
                version,
                createdAt,
                changedAt,
                approvalRequestId,
            ),
        )
        connection.execute(
            """INSERT INTO context_revisions (
                   id, context_record_id, version, value, source_type, source_ref,
                   actor, changed_at, approval_request_id, idempotency_key
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                recordId,
                version,
                value,
                sourceType,
                sourceRef,
                actor,
                changedAt,
                approvalRequestId,
                idempotencyKey,
            ),
        )
        self.auditStateRepository.recordEvent(
            connection=connection,
            actor=actor,
            actionType="UPSERT_CONTEXT_RECORD",
            targetType="context_record",
            targetId=recordId,
            eventStatus="COMPLETE",
            metadata={
                "category": category,
                "sourceType": sourceType,
                "version": str(version),
            },
        )
        return {
            "category": category,
            "id": recordId,
            "key": recordKey,
            "sensitivity": sensitivity,
            "sourceRef": sourceRef,
            "sourceType": sourceType,
            "updatedAt": changedAt,
            "value": value,
            "version": version,
        }

    def _forgetRecord(
        self,
        connection: sqlite3.Connection,
        recordId: str,
        actor: str,
        expectedVersion: int | None,
        approvalRequestId: str | None,
    ) -> dict[str, object]:
        """Erase retained values while preserving a non-content audit tombstone."""
        recordRow = connection.execute(
            """SELECT category, record_key, version FROM context_records
               WHERE id = ? AND status = 'ACTIVE'""",
            (recordId,),
        ).fetchone()
        if recordRow is None:
            raise LookupError("Context record was not found")
        category, recordKey, version = recordRow
        if expectedVersion is not None and expectedVersion != int(version):
            raise ValueError("Context record version changed before approval")
        forgottenAt = datetime.now(UTC).isoformat()
        nextVersion = int(version) + 1
        connection.execute(
            """UPDATE context_records SET value = '[FORGOTTEN]', status = 'FORGOTTEN',
                      version = ?, updated_at = ?, approval_request_id = ?
               WHERE id = ?""",
            (nextVersion, forgottenAt, approvalRequestId, recordId),
        )
        connection.execute(
            """UPDATE context_revisions SET value = '[FORGOTTEN]'
               WHERE context_record_id = ?""",
            (recordId,),
        )
        connection.execute(
            """INSERT INTO context_revisions (
                   id, context_record_id, version, value, source_type, source_ref,
                   actor, changed_at, approval_request_id
               ) VALUES (?, ?, ?, '[FORGOTTEN]', 'approval', ?, ?, ?, ?)""",
            (
                str(uuid4()),
                recordId,
                nextVersion,
                approvalRequestId or "approved-forget",
                actor,
                forgottenAt,
                approvalRequestId,
            ),
        )
        self.auditStateRepository.recordEvent(
            connection=connection,
            actor=actor,
            actionType="FORGET_CONTEXT_RECORD",
            targetType="context_record",
            targetId=recordId,
            eventStatus="COMPLETE",
            metadata={"category": str(category), "version": str(nextVersion)},
        )
        return {
            "category": str(category),
            "id": recordId,
            "key": str(recordKey),
            "status": "FORGOTTEN",
            "version": nextVersion,
        }

    def _refreshMarkdownMirrors(self, connection: sqlite3.Connection) -> None:
        """Regenerate canonical Markdown views without leaking sensitive values."""
        recordRows = connection.execute(
            """SELECT id, category, record_key, value, sensitivity, version,
                      source_type, source_ref, updated_at
               FROM context_records WHERE status = 'ACTIVE'
               ORDER BY category, record_key"""
        ).fetchall()
        records = [self._serializeRecord(recordRow) for recordRow in recordRows]
        recordsByCategory = {
            category: [record for record in records if record["category"] == category]
            for category in CONTEXT_CATEGORIES
        }
        for category in sorted(CONTEXT_CATEGORIES):
            self._writeMarkdownFile(
                self.contextRoot / f"{category}.md",
                self._buildCategoryMarkdown(category, recordsByCategory[category]),
            )
        self._writeMarkdownFile(
            self.contextRoot / "registry.md", self._buildRegistryMarkdown(records)
        )
        self._removeLegacyJsonMirrors()

    def _buildCategoryMarkdown(
        self, category: str, records: list[dict[str, object]]
    ) -> str:
        """Render one category, including values only for ordinary context."""
        categoryTitles = {
            "education-work": "Education and Work",
            "identity": "Identity",
            "important-dates": "Important Dates",
            "owned-items": "Owned Items",
            "people": "People",
            "preferences": "User Preferences",
            "projects-commitments": "Projects and Commitments",
            "user-rules": "User Rules",
        }
        lines = [
            f"# {categoryTitles[category]}",
            "",
            "> This is a generated view. SQLite is authoritative; manual edits are ignored.",
            "",
        ]
        if not records:
            lines.extend(["No confirmed records.", ""])
            return "\n".join(lines)
        for record in records:
            lines.extend(
                [
                    f"## {record['key']}",
                    "",
                    f"- Record ID: `{record['id']}`",
                    f"- Version: {record['version']}",
                    f"- Sensitivity: {record['sensitivity']}",
                    f"- Source: `{record['sourceType']}` / `{record['sourceRef']}`",
                    f"- Updated: {record['updatedAt']}",
                ]
            )
            if record["sensitivity"] == "SENSITIVE":
                lines.extend(["- Value retained only in SQLite.", ""])
            else:
                lines.extend(["", "### Value", ""])
                lines.extend(
                    f"> {valueLine}" if valueLine else ">"
                    for valueLine in str(record["value"]).splitlines()
                )
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _buildRegistryMarkdown(records: list[dict[str, object]]) -> str:
        """Render metadata for every active record without including any values."""
        lines = [
            "# Context Registry",
            "",
            "> This is a generated metadata index. SQLite is authoritative; values are omitted.",
            "",
            "| Record ID | Category | Key | Sensitivity | Version | Source | Updated |",
            "| --- | --- | --- | --- | ---: | --- | --- |",
        ]
        for record in records:
            cells = [
                record["id"],
                record["category"],
                record["key"],
                record["sensitivity"],
                record["version"],
                f"{record['sourceType']} / {record['sourceRef']}",
                record["updatedAt"],
            ]
            escapedCells = [str(cell).replace("|", "\\|") for cell in cells]
            lines.append("| " + " | ".join(escapedCells) + " |")
        if not records:
            lines.append("| — | — | — | — | — | — | — |")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _writeMarkdownFile(mirrorPath: Path, content: str) -> None:
        """Atomically replace one private generated Markdown view."""
        if mirrorPath.exists() and mirrorPath.read_text() == content:
            mirrorPath.chmod(0o600)
            return
        mirrorDraftPath = mirrorPath.with_suffix(".md.pending")
        mirrorDraftPath.write_text(content)
        mirrorDraftPath.chmod(0o600)
        mirrorDraftPath.replace(mirrorPath)
        mirrorPath.chmod(0o600)

    def _removeLegacyJsonMirrors(self) -> None:
        """Remove obsolete generated JSON copies so sensitive values cannot linger."""
        for category in CONTEXT_CATEGORIES:
            legacyCategoryPath = self.contextRoot / category
            if not legacyCategoryPath.is_dir():
                continue
            for legacyMirrorPath in legacyCategoryPath.glob("*.json"):
                legacyMirrorPath.unlink(missing_ok=True)
            try:
                legacyCategoryPath.rmdir()
            except OSError:
                pass

    @staticmethod
    def _serializeRecord(recordRow: tuple[object, ...]) -> dict[str, object]:
        """Map one stable database row to the public context shape."""
        (
            recordId,
            category,
            recordKey,
            value,
            sensitivity,
            version,
            sourceType,
            sourceRef,
            updatedAt,
        ) = recordRow
        return {
            "category": str(category),
            "id": str(recordId),
            "key": str(recordKey),
            "sensitivity": str(sensitivity),
            "sourceRef": str(sourceRef),
            "sourceType": str(sourceType),
            "updatedAt": str(updatedAt),
            "value": str(value),
            "version": int(version),
        }

    @staticmethod
    def _validateRecord(category: str, recordKey: str, value: str) -> tuple[str, str, str]:
        """Reject unknown categories, unsafe mirror names, and unbounded values."""
        if not isinstance(category, str) or category not in CONTEXT_CATEGORIES:
            raise ValueError("Context category is not supported")
        if not isinstance(recordKey, str) or CONTEXT_KEY_PATTERN.fullmatch(recordKey) is None:
            raise ValueError("Context key must be a lowercase safe identifier")
        if not isinstance(value, str) or not value.strip() or len(value) > 10_000:
            raise ValueError("Context value must be between 1 and 10000 characters")
        return category, recordKey, value.strip()

    @staticmethod
    def _validateText(value: str, fieldName: str, maximumLength: int) -> str:
        """Validate bounded non-empty provenance metadata."""
        if not isinstance(value, str) or not value.strip() or len(value) > maximumLength:
            raise ValueError(f"Context {fieldName} is invalid")
        return value.strip()
