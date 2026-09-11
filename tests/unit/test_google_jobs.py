"""Test durable Calendar reminders and conservative email intelligence jobs."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sage_core.database import SageDatabase
from sage_core.google_jobs import GoogleJobRepository
from sage_core.google_state import GoogleStateRepository


def createGoogleState(databasePath: Path) -> tuple[GoogleStateRepository, GoogleJobRepository]:
    """Create repositories with one exact configured Calendar account."""
    database = SageDatabase(databasePath)
    jobRepository = GoogleJobRepository(database)
    stateRepository = GoogleStateRepository(
        database,
        {"personal-work": "owner@example.com"},
        calendarAccountKey="personal-work",
        googleJobRepository=jobRepository,
    )
    return stateRepository, jobRepository


def testCalendarIndexSchedulesOneReminderTenMinutesBeforeStart(tmp_path: Path):
    """A confirmed timed event creates exactly one deterministic delivery."""
    stateRepository, jobRepository = createGoogleState(tmp_path / "sage.db")
    startAt = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    event = {
        "accountKey": "personal-work", "accountEmail": "owner@example.com",
        "eventId": "event-1", "summary": "Placement interview", "description": "Technical round",
        "location": "Room 201", "status": "confirmed", "startAt": startAt.isoformat(),
        "endAt": (startAt + timedelta(hours=1)).isoformat(), "htmlLink": "https://calendar.google.com/event",
        "updatedAt": "2026-09-11T00:00:00Z", "attendees": [],
    }

    assert stateRepository.indexCalendarEvent(event) == "INDEXED"
    assert stateRepository.indexCalendarEvent(event) == "DUPLICATE"
    reminder = jobRepository.claimDueCalendarReminder(startAt - timedelta(minutes=9))

    assert reminder is not None
    assert reminder["dueAt"] == (startAt - timedelta(minutes=10)).isoformat()
    assert reminder["text"].startswith("Upcoming in 10 minutes: Placement interview")
    assert jobRepository.claimDueCalendarReminder(startAt) is None


def testCalendarUpdateReplacesPendingReminderAndCancellationRemovesIt(tmp_path: Path):
    """Changed or cancelled events cannot leave stale reminders behind."""
    stateRepository, jobRepository = createGoogleState(tmp_path / "sage.db")
    startAt = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    event = {
        "accountKey": "personal-work", "accountEmail": "owner@example.com", "eventId": "event-1",
        "summary": "Interview", "description": "", "location": "", "status": "confirmed",
        "startAt": startAt.isoformat(), "endAt": (startAt + timedelta(hours=1)).isoformat(),
        "htmlLink": "", "updatedAt": "2026-09-11T00:00:00Z", "attendees": [],
    }
    stateRepository.indexCalendarEvent(event)
    event["startAt"] = (startAt + timedelta(hours=2)).isoformat()
    event["updatedAt"] = "2026-09-11T01:00:00Z"
    assert stateRepository.indexCalendarEvent(event) == "UPDATED"
    assert jobRepository.claimDueCalendarReminder(startAt) is None
    event["status"] = "cancelled"
    event["updatedAt"] = "2026-09-11T02:00:00Z"
    stateRepository.indexCalendarEvent(event)
    assert jobRepository.claimDueCalendarReminder(startAt + timedelta(hours=3)) is None


def testNewMailCreatesOneConservativeTriageJob(tmp_path: Path):
    """Only a newly indexed message is queued and Gmail labels remain untouched."""
    stateRepository, jobRepository = createGoogleState(tmp_path / "sage.db")
    message = {
        "accountKey": "personal-work", "accountEmail": "owner@example.com", "messageId": "message-1",
        "threadId": "thread-1", "sender": "alerts@example.com", "recipients": ["owner@example.com"],
        "subject": "Payment failed", "snippet": "Your invoice is overdue", "bodyText": "Update billing details.",
        "labelIds": ["INBOX", "UNREAD"], "internalDate": "1789113600000",
    }

    assert stateRepository.indexGmailMessage(message) is True
    assert stateRepository.indexGmailMessage(message) is False
    triageJob = jobRepository.claimEmailTriage()

    assert triageJob is not None
    assert triageJob["messageId"] == "message-1"
    assert triageJob["labelIds"] == ["INBOX", "UNREAD"]
    assert jobRepository.claimEmailTriage() is None


def testFailedReminderReturnsToBacklogAndCompletedTriageDoesNotRepeat(tmp_path: Path):
    """Worker interruption preserves pending work while completed mail stays final."""
    stateRepository, jobRepository = createGoogleState(tmp_path / "sage.db")
    startAt = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    stateRepository.indexCalendarEvent({
        "accountKey": "personal-work", "accountEmail": "owner@example.com", "eventId": "event-1",
        "summary": "Interview", "description": "", "location": "", "status": "confirmed",
        "startAt": startAt.isoformat(), "endAt": (startAt + timedelta(hours=1)).isoformat(),
        "htmlLink": "", "updatedAt": "2026-09-11T00:00:00Z", "attendees": [],
    })
    reminder = jobRepository.claimDueCalendarReminder(startAt)
    assert reminder is not None
    jobRepository.failCalendarReminder("personal-work", "event-1", "TimeoutError", startAt)
    assert jobRepository.claimDueCalendarReminder(startAt) is None
    assert jobRepository.claimDueCalendarReminder(startAt + timedelta(minutes=3)) is not None

    message = {
        "accountKey": "personal-work", "accountEmail": "owner@example.com", "messageId": "message-1",
        "threadId": "thread-1", "sender": "alerts@example.com", "recipients": [], "subject": "Notice",
        "snippet": "", "bodyText": "", "labelIds": ["INBOX"], "internalDate": "1789092000000",
    }
    stateRepository.indexGmailMessage(message)
    assert jobRepository.claimEmailTriage() is not None
    jobRepository.completeEmailTriage("personal-work", "message-1", {"category": "OTHER"})
    assert jobRepository.claimEmailTriage(startAt + timedelta(days=1)) is None


def testBackfillsUpcomingCalendarEventsAfterFeatureDeployment(tmp_path: Path):
    """Events indexed before reminder support become eligible without remote changes."""
    database = SageDatabase(tmp_path / "sage.db")
    jobRepository = GoogleJobRepository(database)
    startAt = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    with database.connectDatabase() as connection:
        connection.execute(
            """INSERT INTO calendar_events (
                   account_key, account_email, event_id, summary, description, location,
                   status, start_at, end_at, html_link, updated_at, attendees_json, indexed_at
               ) VALUES (?, ?, ?, ?, '', '', 'confirmed', ?, ?, '', ?, '[]', ?)""",
            (
                "personal-work", "owner@example.com", "old-event", "Existing interview",
                startAt.isoformat(), (startAt + timedelta(hours=1)).isoformat(),
                "2026-09-11T00:00:00Z", "2026-09-11T00:00:00Z",
            ),
        )

    assert jobRepository.backfillCalendarReminders(startAt - timedelta(days=1)) == 1
    assert jobRepository.backfillCalendarReminders(startAt - timedelta(days=1)) == 0
    assert jobRepository.claimDueCalendarReminder(startAt) is not None
