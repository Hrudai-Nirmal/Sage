"""Test Sage's durable, provenance-aware personal context registry."""

import pytest

from sage_core.context_state import ContextStateRepository
from sage_core.database import SageDatabase


def testCreatesCanonicalMarkdownFilesAndMirrorsStandardValues(tmp_path):
    """The complete inspectable context skeleton exists before any memory is seeded."""
    dataRoot = tmp_path / "SageData"
    database = SageDatabase(dataRoot / "database" / "sage.db")
    repository = ContextStateRepository(database, dataRoot)

    expectedFiles = {
        "education-work.md",
        "identity.md",
        "important-dates.md",
        "owned-items.md",
        "people.md",
        "preferences.md",
        "projects-commitments.md",
        "registry.md",
        "user-rules.md",
    }
    assert {contextPath.name for contextPath in (dataRoot / "context").glob("*.md")} == expectedFiles
    assert all(
        contextPath.stat().st_mode & 0o777 == 0o600
        for contextPath in (dataRoot / "context").glob("*.md")
    )

    firstRecord = repository.upsertRecord(
        category="preferences",
        recordKey="default-language",
        value="English",
        sourceType="telegram-explicit",
        sourceRef="telegram:101",
        actor="telegram-user:8961856168",
    )
    updatedRecord = repository.upsertRecord(
        category="preferences",
        recordKey="default-language",
        value="English unless I ask otherwise",
        sourceType="telegram-explicit",
        sourceRef="telegram:102",
        actor="telegram-user:8961856168",
    )

    assert firstRecord["id"] == updatedRecord["id"]
    assert updatedRecord["version"] == 2
    assert repository.searchRecords("language") == [updatedRecord]
    assert [revision["value"] for revision in repository.listRevisions(firstRecord["id"])] == [
        "English",
        "English unless I ask otherwise",
    ]
    mirrorPath = dataRoot / "context" / "preferences.md"
    assert "default-language" in mirrorPath.read_text()
    assert "English unless I ask otherwise" in mirrorPath.read_text()
    assert "generated view" in mirrorPath.read_text()
    assert mirrorPath.stat().st_mode & 0o777 == 0o600
    with database.connectDatabase() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE target_type = 'context_record'"
        ).fetchone()[0] == 2


def testRepositoryStartupRestoresGeneratedMarkdownFromSqlite(tmp_path):
    """Manual view edits cannot override the authoritative SQLite registry."""
    dataRoot = tmp_path / "SageData"
    database = SageDatabase(dataRoot / "database" / "sage.db")
    ContextStateRepository(database, dataRoot)
    preferencesPath = dataRoot / "context" / "preferences.md"
    preferencesPath.write_text("manually injected value\n")
    preferencesPath.chmod(0o644)

    ContextStateRepository(database, dataRoot)

    assert "manually injected value" not in preferencesPath.read_text()
    assert "No confirmed records." in preferencesPath.read_text()
    assert preferencesPath.stat().st_mode & 0o777 == 0o600


def testSensitiveContextRequiresIndependentApproval(tmp_path):
    """Identity and similarly sensitive categories cannot cross the direct write boundary."""
    dataRoot = tmp_path / "SageData"
    repository = ContextStateRepository(
        SageDatabase(dataRoot / "database" / "sage.db"), dataRoot
    )

    with pytest.raises(PermissionError, match="approval"):
        repository.upsertRecord(
            category="identity",
            recordKey="legal-name",
            value="Test User",
            sourceType="telegram-explicit",
            sourceRef="telegram:103",
            actor="sage-proposal-channel",
        )

    record = repository.upsertRecord(
        category="identity",
        recordKey="legal-name",
        value="Test User",
        sourceType="telegram-explicit",
        sourceRef="telegram:103",
        actor="telegram-user:8961856168",
        hasSensitiveApproval=True,
    )

    assert record["sensitivity"] == "SENSITIVE"
    assert repository.searchRecords("legal name")[0]["value"] == "Test User"
    identityMirror = (dataRoot / "context" / "identity.md").read_text()
    registryMirror = (dataRoot / "context" / "registry.md").read_text()
    assert "legal-name" in identityMirror
    assert record["id"] in identityMirror
    assert "Value retained only in SQLite" in identityMirror
    assert "Test User" not in identityMirror
    assert "Test User" not in registryMirror


def testForgetRequiresApprovalAndRedactsEveryStoredValue(tmp_path):
    """Forgetting removes the managed file and retained content, not merely the search row."""
    dataRoot = tmp_path / "SageData"
    repository = ContextStateRepository(
        SageDatabase(dataRoot / "database" / "sage.db"), dataRoot
    )
    record = repository.upsertRecord(
        category="preferences",
        recordKey="temporary-preference",
        value="Do not retain this",
        sourceType="telegram-explicit",
        sourceRef="telegram:104",
        actor="telegram-user:8961856168",
    )

    with pytest.raises(PermissionError, match="approval"):
        repository.forgetRecord(record["id"], actor="sage-proposal-channel")
    repository.forgetRecord(
        record["id"], actor="telegram-user:8961856168", hasApproval=True
    )

    assert repository.searchRecords("temporary") == []
    assert "temporary-preference" not in (
        dataRoot / "context" / "preferences.md"
    ).read_text()
    with repository.database.connectDatabase() as connection:
        storedValues = connection.execute(
            """SELECT value FROM context_records WHERE id = ?
               UNION ALL
               SELECT value FROM context_revisions WHERE context_record_id = ?""",
            (record["id"], record["id"]),
        ).fetchall()
    assert storedValues
    assert all("Do not retain this" not in str(row[0]) for row in storedValues)


def testBuildsBoundedRelevantContextFromConfirmedRecordsOnly(tmp_path):
    """Every model turn receives global rules plus query-relevant confirmed facts."""
    dataRoot = tmp_path / "SageData"
    repository = ContextStateRepository(
        SageDatabase(dataRoot / "database" / "sage.db"), dataRoot
    )
    for category, recordKey, value in (
        ("user-rules", "tone", "Be highly proactive"),
        ("preferences", "timezone", "Asia/Kolkata"),
        ("projects-commitments", "sage", "Build a local personal assistant"),
        ("projects-commitments", "unrelated", "Plant balcony herbs"),
    ):
        repository.upsertRecord(
            category=category,
            recordKey=recordKey,
            value=value,
            sourceType="telegram-explicit",
            sourceRef="telegram:105",
            actor="telegram-user:8961856168",
        )

    prompt = repository.getRelevantContextPrompt("What is next for the Sage project?")

    assert "Confirmed personal context" in prompt
    assert "Be highly proactive" in prompt
    assert "Asia/Kolkata" in prompt
    assert "Build a local personal assistant" in prompt
    assert "Plant balcony herbs" not in prompt
    assert "Do not infer missing facts" in prompt
