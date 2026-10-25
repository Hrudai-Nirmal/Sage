"""Test Observer event, session, memory, and provenance behavior."""

from datetime import UTC, datetime, timedelta

import pytest

from sage_core.database import SageDatabase
from sage_core.observer.state import ObserverStateRepository


def buildBrowserEvent(
    eventId: str,
    occurredAt: datetime,
    *,
    activeDurationSeconds: int = 30,
    eventType: str = "ACTIVE_PAGE",
    title: str = "Qwen structured output guide",
    url: str = "https://example.com/qwen?utm_source=newsletter&chapter=2",
) -> dict[str, object]:
    """Build one valid browser observation for repository tests."""
    return {
        "activeDurationSeconds": activeDurationSeconds,
        "browserFamily": "CHROME",
        "eventId": eventId,
        "eventType": eventType,
        "occurredAt": occurredAt.isoformat(),
        "pageText": "A bounded guide to structured JSON output.",
        "profileId": "profile-1",
        "profileLabel": "Personal",
        "searchQuery": "qwen api_key=visible-secret structured output",
        "title": title,
        "url": url,
    }


def buildDesktopEvent(
    eventId: str,
    occurredAt: datetime,
    *,
    appBundleId: str = "com.microsoft.VSCode",
    appName: str = "Visual Studio Code",
    windowTitle: str = "observer-state.py — Sage",
) -> dict[str, object]:
    """Build one permitted native app observation for repository tests."""
    return {
        "activeDurationSeconds": 30,
        "appBundleId": appBundleId,
        "appName": appName,
        "eventId": eventId,
        "eventType": "WINDOW_CHANGED",
        "hostId": "hrudais-macbook-pro",
        "occurredAt": occurredAt.isoformat(),
        "windowTitle": windowTitle,
    }


def testRecordsRedactedDeduplicatedEventInOpenSession(tmp_path):
    """Ingress persistence strips tracking and secrets before durable storage."""
    repository = ObserverStateRepository(SageDatabase(tmp_path / "sage.db"))
    occurredAt = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)

    firstReceipt = repository.recordBrowserEvent(buildBrowserEvent("event-1", occurredAt))
    duplicateReceipt = repository.recordBrowserEvent(buildBrowserEvent("event-1", occurredAt))
    storedEvent = repository.getEvent("event-1")

    assert firstReceipt["status"] == "ACCEPTED"
    assert duplicateReceipt["status"] == "DUPLICATE"
    assert storedEvent["url"] == "https://example.com/qwen?chapter=2"
    assert storedEvent["searchQuery"] == "qwen api_key=[REDACTED] structured output"
    assert storedEvent["sessionId"] == firstReceipt["sessionId"]
    assert storedEvent["processingStatus"] == "PENDING"


def testRejectsExcludedAndNonWebLocations(tmp_path):
    """Core fails closed even if a collector submits a forbidden location."""
    repository = ObserverStateRepository(SageDatabase(tmp_path / "sage.db"))
    occurredAt = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)

    with pytest.raises(PermissionError, match="excluded"):
        repository.recordBrowserEvent(
            buildBrowserEvent("event-bank", occurredAt, url="https://bank.example/login")
        )

    with pytest.raises(ValueError, match="HTTP"):
        repository.recordBrowserEvent(
            buildBrowserEvent("event-internal", occurredAt, url="chrome://settings")
        )


def testRecordsRedactedDeduplicatedDesktopEvent(tmp_path):
    """Native metadata shares session storage without pretending to be browser activity."""
    database = SageDatabase(tmp_path / "sage.db")
    repository = ObserverStateRepository(database)
    occurredAt = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)
    event = buildDesktopEvent(
        "desktop-event-1",
        occurredAt,
        windowTitle="Sage password=visible-secret",
    )

    firstReceipt = repository.recordDesktopEvent(event)
    duplicateReceipt = repository.recordDesktopEvent(event)
    storedEvent = repository.getEvent("desktop-event-1")
    with database.connectDatabase() as connection:
        sourceRow = connection.execute(
            """SELECT source_kind, browser_family, profile_id, profile_label
               FROM observer_sources WHERE id = (
                   SELECT source_id FROM observer_events WHERE id = ?
               )""",
            ("desktop-event-1",),
        ).fetchone()

    assert firstReceipt["status"] == "ACCEPTED"
    assert duplicateReceipt == {
        "sessionId": firstReceipt["sessionId"],
        "status": "DUPLICATE",
    }
    assert storedEvent["title"] == "Sage password=[REDACTED]"
    assert storedEvent["appBundleId"] == "com.microsoft.VSCode"
    assert storedEvent["appName"] == "Visual Studio Code"
    assert sourceRow == ("DESKTOP", None, "hrudais-macbook-pro", "Visual Studio Code")


@pytest.mark.parametrize(
    ("appBundleId", "appName"),
    [
        ("com.google.Chrome", "Google Chrome"),
        ("com.apple.keychainaccess", "Keychain Access"),
        ("com.1password.1password", "1Password"),
        ("com.apple.MobileSMS", "Messages"),
        ("com.apple.systempreferences", "System Settings"),
    ],
)
def testRejectsBrowserAndSensitiveDesktopApplications(
    tmp_path, appBundleId, appName
):
    """Desktop collection fails closed where another collector or privacy denylist applies."""
    repository = ObserverStateRepository(SageDatabase(tmp_path / "sage.db"))
    occurredAt = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)

    with pytest.raises(PermissionError, match="excluded"):
        repository.recordDesktopEvent(
            buildDesktopEvent(
                f"event-{appName.lower().replace(' ', '-')}",
                occurredAt,
                appBundleId=appBundleId,
                appName=appName,
            )
        )


def testConsolidatesIndependentEvidenceAndReturnsProvenance(tmp_path):
    """Two independent sessions strengthen one inferred memory instead of duplicating it."""
    repository = ObserverStateRepository(SageDatabase(tmp_path / "sage.db"))
    firstAt = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    secondAt = firstAt + timedelta(days=2)

    firstReceipt = repository.recordBrowserEvent(buildBrowserEvent("event-1", firstAt))
    repository.closeSession(firstReceipt["sessionId"], firstAt + timedelta(minutes=6))
    firstResult = repository.applySessionAnalysis(
        firstReceipt["sessionId"],
        {
            "activityCategory": "LEARNING",
            "candidates": [
                {
                    "confidence": 0.62,
                    "evidenceEventIds": ["event-1"],
                    "isEntertainment": False,
                    "isUncertain": False,
                    "memoryKind": "SEMANTIC",
                    "reasoningSummary": "The user actively read a technical guide.",
                    "subjectKey": "technology:qwen-structured-output",
                    "summary": "Hrudai is learning Qwen structured output.",
                }
            ],
            "summary": "Read a Qwen structured-output guide.",
        },
    )
    assert firstResult["createdMemoryIds"] == []
    assert firstResult["pendingCandidateCount"] == 1
    firstSessionMemories = repository.searchMemories("Qwen", resultLimit=10)
    assert len(firstSessionMemories) == 1
    assert firstSessionMemories[0]["memoryKind"] == "EPISODIC"
    assert firstSessionMemories[0]["trustLevel"] == "OBSERVED"

    secondReceipt = repository.recordBrowserEvent(buildBrowserEvent("event-2", secondAt))
    repository.closeSession(secondReceipt["sessionId"], secondAt + timedelta(minutes=6))
    secondResult = repository.applySessionAnalysis(
        secondReceipt["sessionId"],
        {
            "activityCategory": "LEARNING",
            "candidates": [
                {
                    "confidence": 0.74,
                    "evidenceEventIds": ["event-2"],
                    "isEntertainment": False,
                    "isUncertain": False,
                    "memoryKind": "SEMANTIC",
                    "reasoningSummary": "A separate session revisited the same topic.",
                    "subjectKey": "technology:qwen-structured-output",
                    "summary": "Hrudai is learning Qwen structured output.",
                }
            ],
            "summary": "Revisited Qwen structured-output material.",
        },
    )

    assert len(secondResult["createdMemoryIds"]) == 1
    matches = repository.searchMemories("Qwen structured", resultLimit=10)
    semanticMatches = [item for item in matches if item["memoryKind"] == "SEMANTIC"]
    assert len(semanticMatches) == 1
    assert semanticMatches[0]["trustLevel"] == "INFERRED"
    assert semanticMatches[0]["independentSessionCount"] == 2
    assert semanticMatches[0]["evidenceCount"] == 2
    evidence = repository.listMemoryEvidence(semanticMatches[0]["id"])
    assert {item["eventId"] for item in evidence} == {"event-1", "event-2"}


def testEntertainmentCannotCreateSemanticInterest(tmp_path):
    """Entertainment observations remain minimal episodes regardless of model wording."""
    repository = ObserverStateRepository(SageDatabase(tmp_path / "sage.db"))
    occurredAt = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    receipt = repository.recordBrowserEvent(
        buildBrowserEvent(
            "event-music",
            occurredAt,
            activeDurationSeconds=600,
            eventType="VIDEO_PROGRESS",
            title="Live guitar performance",
            url="https://www.youtube.com/watch?v=music123",
        )
    )
    repository.closeSession(receipt["sessionId"], occurredAt + timedelta(minutes=11))

    result = repository.applySessionAnalysis(
        receipt["sessionId"],
        {
            "activityCategory": "ENTERTAINMENT",
            "candidates": [
                {
                    "confidence": 0.95,
                    "evidenceEventIds": ["event-music"],
                    "isEntertainment": True,
                    "isUncertain": False,
                    "memoryKind": "SEMANTIC",
                    "reasoningSummary": "A music video was watched.",
                    "subjectKey": "interest:guitar-performances",
                    "summary": "Hrudai prefers live guitar performances.",
                }
            ],
            "summary": "Watched a live guitar performance.",
        },
    )

    assert result["createdMemoryIds"] == []
    matches = repository.searchMemories("guitar", resultLimit=10)
    assert len(matches) == 1
    assert matches[0]["memoryKind"] == "EPISODIC"
    assert matches[0]["trustLevel"] == "OBSERVED"
    assert all(item["memoryKind"] != "SEMANTIC" for item in matches)


def testForgetMemoryRemovesEvidenceAndSearchEntry(tmp_path):
    """Forgetting removes provenance and FTS rows in the same transaction."""
    repository = ObserverStateRepository(SageDatabase(tmp_path / "sage.db"))
    occurredAt = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)
    memoryId = "memory-1"
    repository.recordObservedMemory(
        memoryId=memoryId,
        event=buildBrowserEvent("event-1", occurredAt),
        subjectKey="research:dive-watches",
        summary="Researched dive watches.",
    )

    repository.forgetMemory(memoryId, deleteEvidence=False)

    assert repository.searchMemories("dive watches", resultLimit=10) == []
    assert repository.listMemoryEvidence(memoryId) == []
    assert repository.getEvent("event-1")["eventId"] == "event-1"
