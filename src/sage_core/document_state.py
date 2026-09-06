"""Copy explicitly allowed source files into Sage's managed document archive and registry."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


class DocumentStateRepository:
    """Provide a narrow import interface that never writes to external source roots."""

    def __init__(
        self, database: SageDatabase, dataRoot: Path, importRoots: dict[str, Path]
    ) -> None:
        """Configure the managed archive and explicit read-only source-root allowlist."""
        if not isinstance(dataRoot, Path):
            raise TypeError("dataRoot must be a pathlib.Path")
        if any(not isinstance(rootPath, Path) for rootPath in importRoots.values()):
            raise TypeError("importRoots values must be pathlib.Path instances")

        self.archiveRoot = dataRoot / "documents" / "general"
        self.archiveRoot.mkdir(parents=True, exist_ok=True)
        self.importRoots = {
            rootName: rootPath.resolve() for rootName, rootPath in importRoots.items()
        }
        self.database = database
        self.auditStateRepository = AuditStateRepository(database)

    def importDocument(self, sourceRoot: str, relativePath: str) -> dict[str, str]:
        """Copy one allowlisted source file into the archive and register its immutable checksum."""
        sourceFile = self._resolveSourceFile(sourceRoot, relativePath)
        checksum = self._calculateChecksum(sourceFile)

        with self.database.connectDatabase() as connection:
            existingDocument = connection.execute(
                """
                SELECT id, canonical_name, path, checksum
                FROM documents
                WHERE checksum = ?
                """,
                (checksum,),
            ).fetchone()
            if existingDocument is not None:
                return self._serializeDocument(existingDocument)

            canonicalName = f"{sourceFile.stem}-{checksum[:12]}{sourceFile.suffix.lower()}"
            destinationFile = self.archiveRoot / canonicalName
            temporaryFile = self.archiveRoot / f".{canonicalName}.{uuid4().hex}.partial"
            copy2(sourceFile, temporaryFile)
            temporaryFile.replace(destinationFile)

            documentId = str(uuid4())
            importedAt = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT INTO documents (
                    id, canonical_name, original_name, path, source_root,
                    source_relative_path, checksum, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    documentId,
                    canonicalName,
                    sourceFile.name,
                    str(destinationFile),
                    sourceRoot,
                    relativePath,
                    checksum,
                    importedAt,
                ),
            )
            self.auditStateRepository.recordEvent(
                actionType="IMPORT_DOCUMENT",
                actor="sage-proposal-channel",
                connection=connection,
                eventStatus="COMPLETED",
                metadata={"sourceRoot": sourceRoot},
                targetId=documentId,
                targetType="document",
            )

        return {
            "checksum": checksum,
            "id": documentId,
            "name": canonicalName,
            "path": str(destinationFile),
        }

    def listDocuments(self) -> list[dict[str, str]]:
        """List archived documents through the registry rather than filesystem traversal."""
        with self.database.connectDatabase() as connection:
            documentRows = connection.execute(
                """
                SELECT id, canonical_name, path, checksum
                FROM documents
                ORDER BY imported_at
                """
            ).fetchall()

        return [self._serializeDocument(documentRow) for documentRow in documentRows]

    def _resolveSourceFile(self, sourceRoot: str, relativePath: str) -> Path:
        """Resolve a source file only within one named allowlisted import root."""
        rootPath = self.importRoots.get(sourceRoot)
        if rootPath is None:
            raise PermissionError("Source root is not allowlisted")

        sourceFile = (rootPath / relativePath).resolve()
        if not sourceFile.is_relative_to(rootPath):
            raise PermissionError("Source path escapes its allowlisted root")
        if not sourceFile.is_file():
            raise FileNotFoundError("Source file was not found")
        return sourceFile

    def _calculateChecksum(self, sourceFile: Path) -> str:
        """Hash file contents incrementally to avoid loading documents into process memory."""
        digest = sha256()
        with sourceFile.open("rb") as fileHandle:
            while chunk := fileHandle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _serializeDocument(self, documentRow: tuple[str, str, str, str]) -> dict[str, str]:
        """Return a stable document response without source-folder internals."""
        documentId, canonicalName, documentPath, checksum = documentRow
        return {
            "checksum": checksum,
            "id": documentId,
            "name": canonicalName,
            "path": documentPath,
        }
