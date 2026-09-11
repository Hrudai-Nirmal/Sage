"""Persist bounded Google snapshots without mutating remote account state."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase
from sage_core.google_jobs import GoogleJobRepository


class GoogleStateRepository:
    """Own configured Google attribution, snapshot persistence, and local search."""

    def __init__(
        self,
        database: SageDatabase,
        googleAccounts: dict[str, str],
        calendarAccountKey: str | None = None,
        googleJobRepository: GoogleJobRepository | None = None,
    ) -> None:
        """Bind stable account keys to their exact OAuth mailbox identities."""
        self.database = database
        self.googleAccounts = {
            accountKey: accountEmail.casefold()
            for accountKey, accountEmail in googleAccounts.items()
        }
        self.calendarAccountKey = calendarAccountKey
        self.googleJobRepository = googleJobRepository or GoogleJobRepository(database)
        self.auditStateRepository = AuditStateRepository(database)

    def _validateAccount(self, accountKey: str, accountEmail: str) -> None:
        """Reject a snapshot whose claimed identity does not match private configuration."""
        if self.googleAccounts.get(accountKey) != accountEmail.casefold():
            raise PermissionError("Google account attribution is not configured")

    def indexGmailMessage(self, gmailMessage: dict[str, object]) -> bool:
        """Store one immutable Gmail snapshot and report whether it was newly indexed."""
        accountKey = str(gmailMessage["accountKey"])
        accountEmail = str(gmailMessage["accountEmail"]).casefold()
        self._validateAccount(accountKey, accountEmail)
        indexedAt = datetime.now(UTC).isoformat()
        with self.database.connectDatabase() as connection:
            insertResult = connection.execute(
                """INSERT OR IGNORE INTO email_messages (
                    account_key, account_email, message_id, thread_id, sender,
                    recipients_json, subject, snippet, body_text, label_ids_json,
                    internal_date, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    accountKey,
                    accountEmail,
                    str(gmailMessage["messageId"]),
                    str(gmailMessage["threadId"]),
                    str(gmailMessage["sender"]),
                    json.dumps(gmailMessage["recipients"]),
                    str(gmailMessage["subject"]),
                    str(gmailMessage["snippet"]),
                    str(gmailMessage["bodyText"]),
                    json.dumps(gmailMessage["labelIds"]),
                    str(gmailMessage["internalDate"]),
                    indexedAt,
                ),
            )
            if insertResult.rowcount == 1:
                self.auditStateRepository.recordEvent(
                    connection=connection,
                    actor="n8n:google-poller",
                    actionType="INDEX_GMAIL_MESSAGE",
                    targetType="EMAIL_MESSAGE",
                    targetId=f"{accountKey}:{gmailMessage['messageId']}",
                    eventStatus="COMPLETE",
                    metadata={"accountKey": accountKey},
                )
        isNewMessage = insertResult.rowcount == 1
        if isNewMessage:
            self.googleJobRepository.queueEmailTriage(accountKey, str(gmailMessage["messageId"]))
        return isNewMessage

    def indexCalendarEvent(self, calendarEvent: dict[str, object]) -> str:
        """Upsert one personal-work calendar snapshot without changing Google Calendar."""
        accountKey = str(calendarEvent["accountKey"])
        accountEmail = str(calendarEvent["accountEmail"]).casefold()
        self._validateAccount(accountKey, accountEmail)
        if accountKey != self.calendarAccountKey:
            raise PermissionError("Google Calendar account is not configured")
        with self.database.connectDatabase() as connection:
            existingEvent = connection.execute(
                "SELECT updated_at FROM calendar_events WHERE account_key = ? AND event_id = ?",
                (accountKey, str(calendarEvent["eventId"])),
            ).fetchone()
            if existingEvent is not None and str(existingEvent[0]) == str(calendarEvent["updatedAt"]):
                return "DUPLICATE"
            connection.execute(
                """INSERT INTO calendar_events (
                    account_key, account_email, event_id, summary, description,
                    location, status, start_at, end_at, html_link, updated_at,
                    attendees_json, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_key, event_id) DO UPDATE SET
                    summary = excluded.summary, description = excluded.description,
                    location = excluded.location, status = excluded.status,
                    start_at = excluded.start_at, end_at = excluded.end_at,
                    html_link = excluded.html_link, updated_at = excluded.updated_at,
                    attendees_json = excluded.attendees_json, indexed_at = excluded.indexed_at""",
                (
                    accountKey,
                    accountEmail,
                    str(calendarEvent["eventId"]),
                    str(calendarEvent["summary"]),
                    str(calendarEvent["description"]),
                    str(calendarEvent["location"]),
                    str(calendarEvent["status"]),
                    str(calendarEvent["startAt"]),
                    str(calendarEvent["endAt"]),
                    str(calendarEvent["htmlLink"]),
                    str(calendarEvent["updatedAt"]),
                    json.dumps(calendarEvent["attendees"]),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._recordGoogleSnapshot(
                connection,
                "CALENDAR_EVENT",
                f"{accountKey}:{calendarEvent['eventId']}",
                accountKey,
            )
        self.googleJobRepository.scheduleCalendarReminder(calendarEvent)
        return "INDEXED" if existingEvent is None else "UPDATED"

    def indexDriveFile(self, driveFile: dict[str, object]) -> str:
        """Upsert one Drive metadata snapshot without reading or changing file content."""
        accountKey = str(driveFile["accountKey"])
        accountEmail = str(driveFile["accountEmail"]).casefold()
        self._validateAccount(accountKey, accountEmail)
        with self.database.connectDatabase() as connection:
            existingFile = connection.execute(
                "SELECT modified_at FROM drive_files WHERE account_key = ? AND file_id = ?",
                (accountKey, str(driveFile["fileId"])),
            ).fetchone()
            if existingFile is not None and str(existingFile[0]) == str(driveFile["modifiedAt"]):
                return "DUPLICATE"
            connection.execute(
                """INSERT INTO drive_files (
                    account_key, account_email, file_id, name, mime_type, created_at,
                    modified_at, web_view_link, parents_json, owners_json, size, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_key, file_id) DO UPDATE SET
                    name = excluded.name, mime_type = excluded.mime_type,
                    modified_at = excluded.modified_at, web_view_link = excluded.web_view_link,
                    parents_json = excluded.parents_json, owners_json = excluded.owners_json,
                    size = excluded.size, indexed_at = excluded.indexed_at""",
                (
                    accountKey,
                    accountEmail,
                    str(driveFile["fileId"]),
                    str(driveFile["name"]),
                    str(driveFile["mimeType"]),
                    str(driveFile["createdAt"]),
                    str(driveFile["modifiedAt"]),
                    str(driveFile["webViewLink"]),
                    json.dumps(driveFile["parents"]),
                    json.dumps(driveFile["owners"]),
                    str(driveFile["size"]),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._recordGoogleSnapshot(
                connection,
                "DRIVE_FILE",
                f"{accountKey}:{driveFile['fileId']}",
                accountKey,
            )
        return "INDEXED" if existingFile is None else "UPDATED"

    def _recordGoogleSnapshot(
        self,
        connection: sqlite3.Connection,
        targetType: str,
        targetId: str,
        accountKey: str,
    ) -> None:
        """Record a metadata-only Google indexing event in the shared audit trail."""
        self.auditStateRepository.recordEvent(
            connection=connection,
            actor="n8n:google-poller",
            actionType=f"INDEX_{targetType}",
            targetType=targetType,
            targetId=targetId,
            eventStatus="COMPLETE",
            metadata={"accountKey": accountKey},
        )

    def searchGmailMessages(
        self, query: str = "", accountKey: str | None = None, resultLimit: int = 20
    ) -> list[dict[str, object]]:
        """Search bounded locally indexed mail without calling or changing Gmail."""
        if accountKey is not None and accountKey not in self.googleAccounts:
            raise ValueError("Google account key is not configured")
        if resultLimit < 1 or resultLimit > 50:
            raise ValueError("Email result limit must be between 1 and 50")
        queryTerms = [term.casefold() for term in query.split() if term][:10]
        whereClauses = []
        queryValues: list[object] = []
        if accountKey is not None:
            whereClauses.append("account_key = ?")
            queryValues.append(accountKey)
        searchableColumns = (
            "lower(sender || ' ' || recipients_json || ' ' || subject || ' ' || "
            "snippet || ' ' || body_text)"
        )
        for queryTerm in queryTerms:
            whereClauses.append(f"{searchableColumns} LIKE ?")
            queryValues.append(f"%{queryTerm}%")
        whereSql = f"WHERE {' AND '.join(whereClauses)}" if whereClauses else ""
        queryValues.append(resultLimit)
        with self.database.connectDatabase() as connection:
            messageRows = connection.execute(
                f"""SELECT account_email, account_key, body_text, internal_date,
                           label_ids_json, message_id, recipients_json, sender,
                           snippet, subject, thread_id
                    FROM email_messages {whereSql}
                    ORDER BY CAST(internal_date AS INTEGER) DESC LIMIT ?""",
                queryValues,
            ).fetchall()
        return [
            {
                "accountEmail": accountEmail,
                "accountKey": storedAccountKey,
                "bodyText": bodyText,
                "internalDate": internalDate,
                "labelIds": json.loads(labelIdsJson),
                "messageId": messageId,
                "recipients": json.loads(recipientsJson),
                "sender": sender,
                "snippet": snippet,
                "subject": subject,
                "threadId": threadId,
            }
            for (
                accountEmail,
                storedAccountKey,
                bodyText,
                internalDate,
                labelIdsJson,
                messageId,
                recipientsJson,
                sender,
                snippet,
                subject,
                threadId,
            ) in messageRows
        ]

    def searchCalendarEvents(self, query: str = "", resultLimit: int = 20) -> list[dict[str, object]]:
        """Search indexed personal-work calendar events without contacting Google."""
        if resultLimit < 1 or resultLimit > 50:
            raise ValueError("Calendar result limit must be between 1 and 50")
        queryTerms = [term.casefold() for term in query.split() if term][:10]
        whereClauses = []
        queryValues: list[object] = []
        searchableColumns = "lower(summary || ' ' || description || ' ' || location || ' ' || attendees_json)"
        for queryTerm in queryTerms:
            whereClauses.append(f"{searchableColumns} LIKE ?")
            queryValues.append(f"%{queryTerm}%")
        whereSql = f"WHERE {' AND '.join(whereClauses)}" if whereClauses else ""
        queryValues.append(resultLimit)
        with self.database.connectDatabase() as connection:
            eventRows = connection.execute(
                f"""SELECT account_email, account_key, attendees_json, description,
                           end_at, event_id, html_link, location, start_at, status,
                           summary, updated_at
                    FROM calendar_events {whereSql}
                    ORDER BY start_at LIMIT ?""",
                queryValues,
            ).fetchall()
        return [
            {
                "accountEmail": accountEmail,
                "accountKey": accountKey,
                "attendees": json.loads(attendeesJson),
                "description": description,
                "endAt": endAt,
                "eventId": eventId,
                "htmlLink": htmlLink,
                "location": location,
                "startAt": startAt,
                "status": eventStatus,
                "summary": summary,
                "updatedAt": updatedAt,
            }
            for (
                accountEmail,
                accountKey,
                attendeesJson,
                description,
                endAt,
                eventId,
                htmlLink,
                location,
                startAt,
                eventStatus,
                summary,
                updatedAt,
            ) in eventRows
        ]

    def searchDriveFiles(
        self, query: str = "", accountKey: str | None = None, resultLimit: int = 20
    ) -> list[dict[str, object]]:
        """Search indexed Drive metadata across configured accounts without file access."""
        if accountKey is not None and accountKey not in self.googleAccounts:
            raise ValueError("Google account key is not configured")
        if resultLimit < 1 or resultLimit > 50:
            raise ValueError("Drive result limit must be between 1 and 50")
        queryTerms = [term.casefold() for term in query.split() if term][:10]
        whereClauses = []
        queryValues: list[object] = []
        if accountKey is not None:
            whereClauses.append("account_key = ?")
            queryValues.append(accountKey)
        for queryTerm in queryTerms:
            whereClauses.append("lower(name || ' ' || mime_type || ' ' || owners_json) LIKE ?")
            queryValues.append(f"%{queryTerm}%")
        whereSql = f"WHERE {' AND '.join(whereClauses)}" if whereClauses else ""
        queryValues.append(resultLimit)
        with self.database.connectDatabase() as connection:
            fileRows = connection.execute(
                f"""SELECT account_email, account_key, created_at, file_id, mime_type,
                           modified_at, name, owners_json, parents_json, size, web_view_link
                    FROM drive_files {whereSql}
                    ORDER BY modified_at DESC LIMIT ?""",
                queryValues,
            ).fetchall()
        return [
            {
                "accountEmail": accountEmail,
                "accountKey": storedAccountKey,
                "createdAt": createdAt,
                "fileId": fileId,
                "mimeType": mimeType,
                "modifiedAt": modifiedAt,
                "name": name,
                "owners": json.loads(ownersJson),
                "parents": json.loads(parentsJson),
                "size": size,
                "webViewLink": webViewLink,
            }
            for (
                accountEmail,
                storedAccountKey,
                createdAt,
                fileId,
                mimeType,
                modifiedAt,
                name,
                ownersJson,
                parentsJson,
                size,
                webViewLink,
            ) in fileRows
        ]
