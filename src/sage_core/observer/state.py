"""Persist normalized Observer activity and evidence-backed memory atomically."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from sage_core.database import SageDatabase


SUPPORTED_EVENT_TYPES = {
    "ACTIVE_PAGE",
    "IDLE",
    "NAVIGATION",
    "RESUME",
    "SEARCH",
    "VIDEO_PROGRESS",
}
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_NAMES = {"fbclid", "gclid", "mc_cid", "mc_eid"}
SENSITIVE_HOST_MARKERS = (
    "1password",
    "authenticator",
    "bank",
    "bitwarden",
    "coinbase",
    "health",
    "login",
    "paypal",
    "stripe",
)
SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*([^\s&]+)"
)


class ObserverStateRepository:
    """Expose one deep interface for Observer persistence and consolidation."""

    def __init__(self, database: SageDatabase) -> None:
        """Bind the repository to Sage's authoritative SQLite database."""
        self.database = database

    def getMonitoringStatus(
        self, runtimeMode: str, now: datetime | None = None
    ) -> dict[str, object]:
        """Return persisted user intent and the mode-derived effective collection state."""
        normalizedMode = runtimeMode.strip().upper()
        if normalizedMode not in {"NORMAL", "ECO", "SLEEP", "SHUTDOWN"}:
            raise ValueError("Unsupported Sage runtime mode")
        currentTime = now or datetime.now(UTC)
        self._requireAwareTimestamp(currentTime)
        with self.database.connectDatabase() as connection:
            settings = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    """SELECT key, value FROM observer_settings
                       WHERE key IN ('monitoring_state', 'pause_until')"""
                ).fetchall()
            }
            monitoringState = settings.get("monitoring_state", "ON")
            pauseUntil = settings.get("pause_until") or None
            if monitoringState == "PAUSED" and pauseUntil is not None:
                parsedPauseUntil = datetime.fromisoformat(pauseUntil)
                if parsedPauseUntil <= currentTime:
                    monitoringState = "ON"
                    pauseUntil = None
                    self._writeMonitoringSettings(connection, "ON", None, currentTime)
        return {
            "isCollecting": monitoringState == "ON" and normalizedMode in {"NORMAL", "ECO"},
            "monitoringState": monitoringState,
            "pauseUntil": pauseUntil,
            "runtimeMode": normalizedMode,
        }

    def setMonitoringState(
        self,
        monitoringState: str,
        pauseUntil: datetime | None,
        runtimeMode: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Persist explicit Observer on, off, or pause intent across restarts."""
        normalizedState = monitoringState.strip().upper()
        if normalizedState not in {"OFF", "ON", "PAUSED"}:
            raise ValueError("Unsupported Observer monitoring state")
        currentTime = now or datetime.now(UTC)
        self._requireAwareTimestamp(currentTime)
        if pauseUntil is not None:
            self._requireAwareTimestamp(pauseUntil)
        if normalizedState != "PAUSED" and pauseUntil is not None:
            raise ValueError("pauseUntil is valid only for a paused Observer")
        if normalizedState == "PAUSED" and pauseUntil is not None and pauseUntil <= currentTime:
            normalizedState = "ON"
            pauseUntil = None
        with self.database.connectDatabase() as connection:
            self._writeMonitoringSettings(
                connection, normalizedState, pauseUntil, currentTime
            )
        return self.getMonitoringStatus(runtimeMode, currentTime)

    def recordBrowserEvent(self, browserEvent: dict[str, object]) -> dict[str, str]:
        """Normalize and store one idempotent browser event in an activity session."""
        normalizedEvent = self._normalizeBrowserEvent(browserEvent)
        with self.database.connectDatabase() as connection:
            duplicateRow = connection.execute(
                "SELECT session_id FROM observer_events WHERE id = ?",
                (normalizedEvent["eventId"],),
            ).fetchone()
            if duplicateRow is not None:
                return {"sessionId": str(duplicateRow[0]), "status": "DUPLICATE"}

            sourceId = self._upsertSource(connection, normalizedEvent)
            sessionId = self._getOrCreateSession(connection, sourceId, normalizedEvent["occurredAt"])
            receivedAt = datetime.now(UTC)
            pageText = normalizedEvent.get("pageText")
            connection.execute(
                """INSERT INTO observer_events (
                       id, source_id, session_id, event_type, occurred_at, received_at,
                       url, domain, title, page_text, search_query, active_duration_seconds,
                       video_json, content_hash, processing_status, raw_expires_at,
                       extract_expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
                (
                    normalizedEvent["eventId"],
                    sourceId,
                    sessionId,
                    normalizedEvent["eventType"],
                    normalizedEvent["occurredAt"].isoformat(),
                    receivedAt.isoformat(),
                    normalizedEvent.get("url"),
                    normalizedEvent.get("domain"),
                    normalizedEvent.get("title"),
                    pageText,
                    normalizedEvent.get("searchQuery"),
                    normalizedEvent.get("activeDurationSeconds"),
                    json.dumps(normalizedEvent.get("video"), sort_keys=True)
                    if normalizedEvent.get("video") is not None
                    else None,
                    normalizedEvent["contentHash"],
                    (normalizedEvent["occurredAt"] + timedelta(days=30)).isoformat(),
                    (normalizedEvent["occurredAt"] + timedelta(days=14)).isoformat()
                    if pageText
                    else None,
                ),
            )
            connection.execute(
                """UPDATE observer_sessions
                   SET last_event_at = ?, event_count = event_count + 1
                   WHERE id = ?""",
                (normalizedEvent["occurredAt"].isoformat(), sessionId),
            )
            return {"sessionId": sessionId, "status": "ACCEPTED"}

    def getEvent(self, eventId: str) -> dict[str, object]:
        """Return one normalized event for local diagnostics and evidence review."""
        if not eventId.strip():
            raise ValueError("eventId is required")
        with self.database.connectDatabase() as connection:
            row = connection.execute(
                """SELECT id, session_id, url, title, search_query, processing_status
                   FROM observer_events WHERE id = ?""",
                (eventId,),
            ).fetchone()
        if row is None:
            raise LookupError("Observer event was not found")
        return {
            "eventId": str(row[0]),
            "sessionId": str(row[1]),
            "url": row[2],
            "title": row[3],
            "searchQuery": row[4],
            "processingStatus": str(row[5]),
        }

    def closeSession(self, sessionId: str, endedAt: datetime) -> None:
        """Close one exact open session at a timezone-aware boundary."""
        if not sessionId.strip():
            raise ValueError("sessionId is required")
        self._requireAwareTimestamp(endedAt)
        with self.database.connectDatabase() as connection:
            cursor = connection.execute(
                """UPDATE observer_sessions
                   SET status = 'CLOSED', ended_at = ?
                   WHERE id = ? AND status = 'OPEN'""",
                (endedAt.isoformat(), sessionId),
            )
            if cursor.rowcount != 1:
                raise LookupError("Open Observer session was not found")

    def closeInactiveSessions(self, now: datetime) -> int:
        """Close every session with no event for five minutes and return its count."""
        self._requireAwareTimestamp(now)
        inactiveBefore = now - timedelta(minutes=5)
        with self.database.connectDatabase() as connection:
            cursor = connection.execute(
                """UPDATE observer_sessions
                   SET status = 'CLOSED', ended_at = last_event_at
                   WHERE status = 'OPEN' AND last_event_at <= ?""",
                (inactiveBefore.isoformat(),),
            )
            return cursor.rowcount

    def claimPendingSession(self, now: datetime) -> dict[str, object] | None:
        """Atomically claim one closed session and recover an interrupted stale claim."""
        self._requireAwareTimestamp(now)
        staleBefore = now - timedelta(minutes=15)
        with self.database.connectDatabase() as connection:
            connection.execute(
                """UPDATE observer_sessions
                   SET analysis_status = 'PENDING', analysis_claimed_at = NULL,
                       error_type = 'InterruptedClaim'
                   WHERE analysis_status = 'PROCESSING' AND analysis_claimed_at < ?""",
                (staleBefore.isoformat(),),
            )
            sessionRow = connection.execute(
                """SELECT id, source_id, started_at, last_event_at
                   FROM observer_sessions
                   WHERE status = 'CLOSED' AND analysis_status = 'PENDING'
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   ORDER BY started_at ASC LIMIT 1""",
                (now.isoformat(),),
            ).fetchone()
            if sessionRow is None:
                return None
            sessionId = str(sessionRow[0])
            cursor = connection.execute(
                """UPDATE observer_sessions
                   SET analysis_status = 'PROCESSING', analysis_claimed_at = ?,
                       analysis_attempts = analysis_attempts + 1, error_type = NULL
                   WHERE id = ? AND analysis_status = 'PENDING'""",
                (now.isoformat(), sessionId),
            )
            if cursor.rowcount != 1:
                return None
            eventRows = connection.execute(
                """SELECT id, event_type, occurred_at, url, title, page_text,
                          search_query, active_duration_seconds, video_json
                   FROM observer_events WHERE session_id = ?
                   ORDER BY occurred_at ASC LIMIT 500""",
                (sessionId,),
            ).fetchall()
        return {
            "events": [
                {
                    "activeDurationSeconds": eventRow[7],
                    "eventId": str(eventRow[0]),
                    "eventType": str(eventRow[1]),
                    "occurredAt": str(eventRow[2]),
                    "pageText": eventRow[5],
                    "searchQuery": eventRow[6],
                    "title": eventRow[4],
                    "url": eventRow[3],
                    "video": json.loads(str(eventRow[8])) if eventRow[8] else None,
                }
                for eventRow in eventRows
            ],
            "lastEventAt": str(sessionRow[3]),
            "sessionId": sessionId,
            "sourceId": str(sessionRow[1]),
            "startedAt": str(sessionRow[2]),
        }

    def releaseSessionAfterFailure(
        self, sessionId: str, errorType: str, nextAttemptAt: datetime
    ) -> None:
        """Return a failed claim to the durable queue without losing its events."""
        if not sessionId.strip() or not errorType.strip():
            raise ValueError("Failure release fields are required")
        self._requireAwareTimestamp(nextAttemptAt)
        with self.database.connectDatabase() as connection:
            cursor = connection.execute(
                """UPDATE observer_sessions
                   SET analysis_status = 'PENDING', analysis_claimed_at = NULL,
                       next_attempt_at = ?, error_type = ?
                   WHERE id = ? AND analysis_status = 'PROCESSING'""",
                (nextAttemptAt.isoformat(), errorType[:200], sessionId),
            )
            if cursor.rowcount != 1:
                raise LookupError("Claimed Observer session was not found")

    def getSession(self, sessionId: str) -> dict[str, object]:
        """Return bounded session processing state for health and tests."""
        if not sessionId.strip():
            raise ValueError("sessionId is required")
        with self.database.connectDatabase() as connection:
            row = connection.execute(
                """SELECT id, status, analysis_status, analysis_attempts, error_type
                   FROM observer_sessions WHERE id = ?""",
                (sessionId,),
            ).fetchone()
        if row is None:
            raise LookupError("Observer session was not found")
        return {
            "id": str(row[0]),
            "status": str(row[1]),
            "analysisStatus": str(row[2]),
            "analysisAttempts": int(row[3]),
            "errorType": row[4],
        }

    def applySessionAnalysis(
        self, sessionId: str, analysis: dict[str, object]
    ) -> dict[str, object]:
        """Validate Iris output and consolidate eligible candidates transactionally."""
        normalizedAnalysis = self._normalizeAnalysis(analysis)
        createdMemoryIds: list[str] = []
        createdEpisodicMemoryId: str | None = None
        with self.database.connectDatabase() as connection:
            sessionRow = connection.execute(
                """SELECT status, started_at FROM observer_sessions WHERE id = ?""",
                (sessionId,),
            ).fetchone()
            if sessionRow is None:
                raise LookupError("Observer session was not found")
            if str(sessionRow[0]) != "CLOSED":
                raise ValueError("Observer session must be closed before analysis")
            eventRows = connection.execute(
                """SELECT id, occurred_at, title, url, event_type,
                          active_duration_seconds
                   FROM observer_events
                   WHERE session_id = ?""",
                (sessionId,),
            ).fetchall()
            eventById = {str(row[0]): row for row in eventRows}
            connection.execute(
                """UPDATE observer_sessions
                   SET activity_category = ?, summary = ? WHERE id = ?""",
                (
                    normalizedAnalysis["activityCategory"],
                    normalizedAnalysis["summary"],
                    sessionId,
                ),
            )
            if self._isMeaningfulSession(eventRows):
                createdEpisodicMemoryId = self._recordObservedEpisode(
                    connection,
                    sessionId,
                    normalizedAnalysis["activityCategory"],
                    normalizedAnalysis["summary"],
                    eventRows,
                )
            for candidate in normalizedAnalysis["candidates"]:
                evidenceIds = candidate["evidenceEventIds"]
                if any(eventId not in eventById for eventId in evidenceIds):
                    raise ValueError("Analysis evidence must belong to the analyzed session")
                if candidate["isEntertainment"]:
                    continue
                memoryId = self._recordCandidate(
                    connection,
                    sessionId,
                    candidate,
                    eventById,
                )
                if memoryId is not None:
                    createdMemoryIds.append(memoryId)
            connection.execute(
                """UPDATE observer_events SET processing_status = 'PROCESSED'
                   WHERE session_id = ?""",
                (sessionId,),
            )
            connection.execute(
                """UPDATE observer_sessions
                   SET analysis_status = 'COMPLETE', analysis_claimed_at = NULL,
                       next_attempt_at = NULL, error_type = NULL
                   WHERE id = ?""",
                (sessionId,),
            )
            pendingCandidateCount = int(
                connection.execute(
                    "SELECT COUNT(*) FROM observer_memory_candidates"
                ).fetchone()[0]
            )
        return {
            "createdEpisodicMemoryId": createdEpisodicMemoryId,
            "createdMemoryIds": createdMemoryIds,
            "pendingCandidateCount": pendingCandidateCount,
        }

    def recordObservedMemory(
        self,
        memoryId: str,
        event: dict[str, object],
        subjectKey: str,
        summary: str,
    ) -> None:
        """Store a direct observed episode with one normalized evidence event."""
        if not memoryId.strip() or not subjectKey.strip() or not summary.strip():
            raise ValueError("Observed memory fields are required")
        receipt = self.recordBrowserEvent(event)
        now = datetime.now(UTC).isoformat()
        with self.database.connectDatabase() as connection:
            connection.execute(
                """INSERT INTO observer_memories (
                       id, memory_kind, trust_level, subject_key, summary, confidence,
                       reasoning_summary, evidence_count, independent_session_count,
                       is_uncertain, first_seen_at, last_seen_at, expires_at, status,
                       created_at, updated_at
                   ) VALUES (?, 'EPISODIC', 'OBSERVED', ?, ?, 1.0, ?, 1, 1, 0,
                             ?, ?, ?, 'ACTIVE', ?, ?)""",
                (
                    memoryId,
                    subjectKey,
                    summary,
                    "Directly observed permitted activity.",
                    str(event["occurredAt"]),
                    str(event["occurredAt"]),
                    (datetime.fromisoformat(str(event["occurredAt"])) + timedelta(days=365)).isoformat(),
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO observer_memory_evidence (
                       memory_id, event_id, session_id, evidence_excerpt, observed_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    memoryId,
                    str(event["eventId"]),
                    receipt["sessionId"],
                    str(event.get("title", ""))[:500],
                    str(event["occurredAt"]),
                ),
            )
            self._indexMemory(connection, memoryId, subjectKey, summary)

    def searchMemories(self, query: str, resultLimit: int) -> list[dict[str, object]]:
        """Search active Observer memories through FTS5 with bounded output."""
        if resultLimit < 1 or resultLimit > 100:
            raise ValueError("resultLimit must be between 1 and 100")
        normalizedQuery = query.strip()
        with self.database.connectDatabase() as connection:
            if normalizedQuery:
                ftsQuery = " OR ".join(
                    f'"{token.replace(chr(34), chr(34) * 2)}"'
                    for token in normalizedQuery.split()
                )
                rows = connection.execute(
                    """SELECT memory.id, memory.memory_kind, memory.trust_level,
                              memory.subject_key, memory.summary, memory.confidence,
                              memory.evidence_count, memory.independent_session_count,
                              memory.is_uncertain, memory.first_seen_at, memory.last_seen_at
                       FROM observer_memory_fts AS search
                       JOIN observer_memories AS memory ON memory.id = search.memory_id
                       WHERE observer_memory_fts MATCH ? AND memory.status = 'ACTIVE'
                       ORDER BY bm25(observer_memory_fts), memory.last_seen_at DESC
                       LIMIT ?""",
                    (ftsQuery, resultLimit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT id, memory_kind, trust_level, subject_key, summary,
                              confidence, evidence_count, independent_session_count,
                              is_uncertain, first_seen_at, last_seen_at
                       FROM observer_memories WHERE status = 'ACTIVE'
                       ORDER BY last_seen_at DESC LIMIT ?""",
                    (resultLimit,),
                ).fetchall()
        return [self._serializeMemory(row) for row in rows]

    def listMemoryEvidence(self, memoryId: str) -> list[dict[str, object]]:
        """List bounded provenance edges for one memory."""
        if not memoryId.strip():
            raise ValueError("memoryId is required")
        with self.database.connectDatabase() as connection:
            rows = connection.execute(
                """SELECT event_id, session_id, evidence_excerpt, observed_at
                   FROM observer_memory_evidence WHERE memory_id = ?
                   ORDER BY observed_at ASC LIMIT 100""",
                (memoryId,),
            ).fetchall()
        return [
            {
                "eventId": str(row[0]),
                "sessionId": str(row[1]),
                "evidenceExcerpt": str(row[2]),
                "observedAt": str(row[3]),
            }
            for row in rows
        ]

    def forgetMemory(self, memoryId: str, deleteEvidence: bool) -> None:
        """Forget one memory and optionally remove unshared raw evidence."""
        if not memoryId.strip():
            raise ValueError("memoryId is required")
        with self.database.connectDatabase() as connection:
            memoryRow = connection.execute(
                "SELECT id FROM observer_memories WHERE id = ?", (memoryId,)
            ).fetchone()
            if memoryRow is None:
                raise LookupError("Observer memory was not found")
            eventIds = [
                str(row[0])
                for row in connection.execute(
                    "SELECT event_id FROM observer_memory_evidence WHERE memory_id = ?",
                    (memoryId,),
                ).fetchall()
            ]
            connection.execute(
                "DELETE FROM observer_memory_fts WHERE memory_id = ?", (memoryId,)
            )
            connection.execute("DELETE FROM observer_memories WHERE id = ?", (memoryId,))
            if deleteEvidence:
                for eventId in eventIds:
                    sharedCount = int(
                        connection.execute(
                            """SELECT COUNT(*) FROM observer_memory_evidence
                               WHERE event_id = ?""",
                            (eventId,),
                        ).fetchone()[0]
                    )
                    if sharedCount == 0:
                        connection.execute("DELETE FROM observer_events WHERE id = ?", (eventId,))

    def _normalizeBrowserEvent(self, browserEvent: dict[str, object]) -> dict[str, Any]:
        """Validate a direct repository call and remove unsafe or noisy content."""
        requiredFields = ("browserFamily", "eventId", "eventType", "occurredAt", "profileId")
        for fieldName in requiredFields:
            if not str(browserEvent.get(fieldName, "")).strip():
                raise ValueError(f"{fieldName} is required")
        eventType = str(browserEvent["eventType"]).upper()
        if eventType not in SUPPORTED_EVENT_TYPES:
            raise ValueError("Unsupported Observer event type")
        occurredAt = datetime.fromisoformat(str(browserEvent["occurredAt"]))
        self._requireAwareTimestamp(occurredAt)
        normalizedEvent: dict[str, Any] = {
            "activeDurationSeconds": browserEvent.get("activeDurationSeconds"),
            "browserFamily": str(browserEvent["browserFamily"]).upper(),
            "eventId": str(browserEvent["eventId"]),
            "eventType": eventType,
            "occurredAt": occurredAt,
            "pageText": self._redactText(str(browserEvent.get("pageText", ""))) or None,
            "profileId": str(browserEvent["profileId"]),
            "profileLabel": str(browserEvent.get("profileLabel", "")).strip() or None,
            "searchQuery": self._redactText(str(browserEvent.get("searchQuery", ""))) or None,
            "title": self._redactText(str(browserEvent.get("title", ""))) or None,
            "video": browserEvent.get("video"),
        }
        rawUrl = str(browserEvent.get("url", "")).strip()
        if rawUrl:
            normalizedUrl, domain = self._normalizeUrl(rawUrl)
            normalizedEvent["url"] = normalizedUrl
            normalizedEvent["domain"] = domain
        hashPayload = json.dumps(
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in normalizedEvent.items()
            },
            default=str,
            sort_keys=True,
        )
        normalizedEvent["contentHash"] = hashlib.sha256(hashPayload.encode()).hexdigest()
        return normalizedEvent

    def _writeMonitoringSettings(
        self,
        connection: sqlite3.Connection,
        monitoringState: str,
        pauseUntil: datetime | None,
        updatedAt: datetime,
    ) -> None:
        """Update the two Observer control keys in one transaction."""
        connection.execute(
            """INSERT INTO observer_settings (key, value, updated_at)
               VALUES ('monitoring_state', ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value, updated_at = excluded.updated_at""",
            (monitoringState, updatedAt.isoformat()),
        )
        connection.execute(
            """INSERT INTO observer_settings (key, value, updated_at)
               VALUES ('pause_until', ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value, updated_at = excluded.updated_at""",
            (pauseUntil.isoformat() if pauseUntil is not None else "", updatedAt.isoformat()),
        )

    def _normalizeAnalysis(self, analysis: dict[str, object]) -> dict[str, Any]:
        """Reject free-form or policy-violating model output before persistence."""
        allowedAnalysisFields = {"activityCategory", "candidates", "summary"}
        if set(analysis) - allowedAnalysisFields:
            raise ValueError("Observer analysis contains unknown fields")
        activityCategory = str(analysis.get("activityCategory", "")).strip().upper()
        summary = str(analysis.get("summary", "")).strip()
        candidates = analysis.get("candidates")
        if not activityCategory or not summary or not isinstance(candidates, list):
            raise ValueError("Observer analysis is incomplete")
        normalizedCandidates: list[dict[str, Any]] = []
        for rawCandidate in candidates:
            if not isinstance(rawCandidate, dict):
                raise ValueError("Observer memory candidate must be an object")
            allowedCandidateFields = {
                "confidence",
                "evidenceEventIds",
                "isEntertainment",
                "isUncertain",
                "memoryKind",
                "reasoningSummary",
                "subjectKey",
                "summary",
            }
            if set(rawCandidate) - allowedCandidateFields:
                raise ValueError("Observer analysis contains unknown fields")
            memoryKind = str(rawCandidate.get("memoryKind", "")).upper()
            subjectKey = str(rawCandidate.get("subjectKey", "")).strip().lower()
            candidateSummary = str(rawCandidate.get("summary", "")).strip()
            reasoningSummary = str(rawCandidate.get("reasoningSummary", "")).strip()
            evidenceIds = rawCandidate.get("evidenceEventIds")
            confidence = float(rawCandidate.get("confidence", -1))
            if memoryKind not in {"EPISODIC", "SEMANTIC"}:
                raise ValueError("Unsupported Observer memory kind")
            if not subjectKey or not candidateSummary or not reasoningSummary:
                raise ValueError("Observer memory candidate is incomplete")
            if not isinstance(evidenceIds, list) or not evidenceIds:
                raise ValueError("Observer memory candidate requires evidence")
            if confidence < 0 or confidence > 1:
                raise ValueError("Observer confidence must be between 0 and 1")
            loweredText = f"{subjectKey} {candidateSummary}".lower()
            prohibitedMarkers = (
                "bank balance",
                "credit card",
                "diagnosis",
                "has purchased",
                "legal problem",
                "password",
                "political affiliation",
                "purchase intent",
                "religion",
                "sexuality",
            )
            if any(marker in loweredText for marker in prohibitedMarkers):
                raise PermissionError("Observer candidate violates memory policy")
            normalizedCandidates.append(
                {
                    "confidence": confidence,
                    "evidenceEventIds": [str(eventId) for eventId in evidenceIds],
                    "isEntertainment": bool(rawCandidate.get("isEntertainment", False)),
                    "isUncertain": bool(rawCandidate.get("isUncertain", False)),
                    "memoryKind": memoryKind,
                    "reasoningSummary": reasoningSummary,
                    "subjectKey": subjectKey,
                    "summary": candidateSummary,
                }
            )
        return {
            "activityCategory": activityCategory,
            "candidates": normalizedCandidates,
            "summary": summary,
        }

    def _recordCandidate(
        self,
        connection: sqlite3.Connection,
        sessionId: str,
        candidate: dict[str, Any],
        eventById: dict[str, sqlite3.Row | tuple[object, ...]],
    ) -> str | None:
        """Accumulate independent evidence and materialize one deduplicated inference."""
        observedAt = max(str(eventById[eventId][1]) for eventId in candidate["evidenceEventIds"])
        existingMemory = connection.execute(
            """SELECT id FROM observer_memories
               WHERE memory_kind = ? AND trust_level = 'INFERRED'
                 AND subject_key = ? AND status = 'ACTIVE'""",
            (candidate["memoryKind"], candidate["subjectKey"]),
        ).fetchone()
        if existingMemory is not None:
            memoryId = str(existingMemory[0])
            self._attachEvidence(connection, memoryId, sessionId, candidate, eventById)
            self._refreshMemory(connection, memoryId, candidate)
            return memoryId

        connection.execute(
            """INSERT OR REPLACE INTO observer_memory_candidates (
                   id, memory_kind, subject_key, summary, confidence, reasoning_summary,
                   session_id, evidence_event_ids_json, is_uncertain, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                candidate["memoryKind"],
                candidate["subjectKey"],
                candidate["summary"],
                min(candidate["confidence"], 0.35) if candidate["isUncertain"] else candidate["confidence"],
                candidate["reasoningSummary"],
                sessionId,
                json.dumps(candidate["evidenceEventIds"]),
                int(candidate["isUncertain"]),
                observedAt,
            ),
        )
        candidateRows = connection.execute(
            """SELECT summary, confidence, reasoning_summary, session_id,
                      evidence_event_ids_json, is_uncertain, observed_at
               FROM observer_memory_candidates
               WHERE memory_kind = ? AND subject_key = ?
               ORDER BY observed_at ASC""",
            (candidate["memoryKind"], candidate["subjectKey"]),
        ).fetchall()
        requiredSessions = 1 if candidate["isUncertain"] else 2
        if len(candidateRows) < requiredSessions:
            return None

        memoryId = str(uuid4())
        firstSeenAt = str(candidateRows[0][6])
        lastSeenAt = str(candidateRows[-1][6])
        confidence = min(
            0.95,
            max(float(row[1]) for row in candidateRows) + 0.08 * (len(candidateRows) - 1),
        )
        if candidate["isUncertain"]:
            confidence = min(confidence, 0.35)
        now = datetime.now(UTC).isoformat()
        connection.execute(
            """INSERT INTO observer_memories (
                   id, memory_kind, trust_level, subject_key, summary, confidence,
                   reasoning_summary, evidence_count, independent_session_count,
                   is_uncertain, first_seen_at, last_seen_at, expires_at, status,
                   created_at, updated_at
               ) VALUES (?, ?, 'INFERRED', ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)""",
            (
                memoryId,
                candidate["memoryKind"],
                candidate["subjectKey"],
                candidateRows[-1][0],
                confidence,
                candidateRows[-1][2],
                len(candidateRows),
                int(any(bool(row[5]) for row in candidateRows)),
                firstSeenAt,
                lastSeenAt,
                (datetime.fromisoformat(lastSeenAt) + timedelta(days=30)).isoformat(),
                now,
                now,
            ),
        )
        for candidateRow in candidateRows:
            rowSessionId = str(candidateRow[3])
            rowEventIds = json.loads(str(candidateRow[4]))
            rowEvents = {
                str(row[0]): row
                for row in connection.execute(
                    """SELECT id, occurred_at, title, url FROM observer_events
                       WHERE session_id = ?""",
                    (rowSessionId,),
                ).fetchall()
            }
            self._attachEvidence(
                connection,
                memoryId,
                rowSessionId,
                candidate | {"evidenceEventIds": rowEventIds},
                rowEvents,
            )
        self._refreshMemory(connection, memoryId, candidate)
        connection.execute(
            """DELETE FROM observer_memory_candidates
               WHERE memory_kind = ? AND subject_key = ?""",
            (candidate["memoryKind"], candidate["subjectKey"]),
        )
        return memoryId

    def _isMeaningfulSession(
        self, eventRows: list[sqlite3.Row | tuple[object, ...]]
    ) -> bool:
        """Apply deterministic duration gates before any episode is retained."""
        activeSeconds = sum(int(row[5] or 0) for row in eventRows)
        hasQualifyingVideo = any(str(row[4]) == "VIDEO_PROGRESS" for row in eventRows)
        hasActivePage = any(
            str(row[4]) == "ACTIVE_PAGE" and int(row[5] or 0) >= 30
            for row in eventRows
        )
        return hasQualifyingVideo or hasActivePage or activeSeconds >= 120

    def _recordObservedEpisode(
        self,
        connection: sqlite3.Connection,
        sessionId: str,
        activityCategory: str,
        summary: str,
        eventRows: list[sqlite3.Row | tuple[object, ...]],
    ) -> str:
        """Persist one idempotent direct episode for a meaningful analyzed session."""
        memoryId = str(uuid5(NAMESPACE_URL, f"observer-session:{sessionId}"))
        existingRow = connection.execute(
            "SELECT id FROM observer_memories WHERE id = ?", (memoryId,)
        ).fetchone()
        if existingRow is not None:
            return memoryId
        firstSeenAt = min(str(row[1]) for row in eventRows)
        lastSeenAt = max(str(row[1]) for row in eventRows)
        retentionDays = 30 if activityCategory == "ENTERTAINMENT" else 365
        now = datetime.now(UTC).isoformat()
        connection.execute(
            """INSERT INTO observer_memories (
                   id, memory_kind, trust_level, subject_key, summary, confidence,
                   reasoning_summary, evidence_count, independent_session_count,
                   is_uncertain, first_seen_at, last_seen_at, expires_at, status,
                   created_at, updated_at
               ) VALUES (?, 'EPISODIC', 'OBSERVED', ?, ?, 1.0, ?, 0, 1, 0,
                         ?, ?, ?, 'ACTIVE', ?, ?)""",
            (
                memoryId,
                f"session:{sessionId}",
                summary,
                "Direct summary of permitted activity in one analyzed session.",
                firstSeenAt,
                lastSeenAt,
                (datetime.fromisoformat(lastSeenAt) + timedelta(days=retentionDays)).isoformat(),
                now,
                now,
            ),
        )
        for eventRow in eventRows[:100]:
            evidenceExcerpt = str(eventRow[2] or eventRow[3] or "Observed activity")[:500]
            connection.execute(
                """INSERT INTO observer_memory_evidence (
                       memory_id, event_id, session_id, evidence_excerpt, observed_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (memoryId, str(eventRow[0]), sessionId, evidenceExcerpt, str(eventRow[1])),
            )
        evidenceCount = int(
            connection.execute(
                """SELECT COUNT(*) FROM observer_memory_evidence
                   WHERE memory_id = ?""",
                (memoryId,),
            ).fetchone()[0]
        )
        connection.execute(
            """UPDATE observer_memories SET evidence_count = ? WHERE id = ?""",
            (evidenceCount, memoryId),
        )
        self._indexMemory(connection, memoryId, f"session:{sessionId}", summary)
        return memoryId

    def _attachEvidence(
        self,
        connection: sqlite3.Connection,
        memoryId: str,
        sessionId: str,
        candidate: dict[str, Any],
        eventById: dict[str, sqlite3.Row | tuple[object, ...]],
    ) -> None:
        """Attach only evidence validated against its source session."""
        for eventId in candidate["evidenceEventIds"]:
            eventRow = eventById[eventId]
            excerpt = str(eventRow[2] or eventRow[3] or "Observed activity")[:500]
            connection.execute(
                """INSERT OR IGNORE INTO observer_memory_evidence (
                       memory_id, event_id, session_id, evidence_excerpt, observed_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (memoryId, eventId, sessionId, excerpt, str(eventRow[1])),
            )

    def _refreshMemory(
        self,
        connection: sqlite3.Connection,
        memoryId: str,
        candidate: dict[str, Any],
    ) -> None:
        """Derive counters from provenance rather than trusting model-provided counts."""
        counts = connection.execute(
            """SELECT COUNT(*), COUNT(DISTINCT session_id), MIN(observed_at), MAX(observed_at)
               FROM observer_memory_evidence WHERE memory_id = ?""",
            (memoryId,),
        ).fetchone()
        evidenceCount = int(counts[0])
        sessionCount = int(counts[1])
        currentConfidence = float(
            connection.execute(
                "SELECT confidence FROM observer_memories WHERE id = ?", (memoryId,)
            ).fetchone()[0]
        )
        confidence = min(0.95, max(currentConfidence, candidate["confidence"]) + 0.04)
        if candidate["isUncertain"]:
            confidence = min(confidence, 0.35)
        now = datetime.now(UTC).isoformat()
        connection.execute(
            """UPDATE observer_memories
               SET summary = ?, confidence = ?, reasoning_summary = ?,
                   evidence_count = ?, independent_session_count = ?,
                   first_seen_at = ?, last_seen_at = ?, expires_at = ?, updated_at = ?
               WHERE id = ?""",
            (
                candidate["summary"],
                confidence,
                candidate["reasoningSummary"],
                evidenceCount,
                sessionCount,
                counts[2],
                counts[3],
                (datetime.fromisoformat(str(counts[3])) + timedelta(days=30)).isoformat(),
                now,
                memoryId,
            ),
        )
        connection.execute(
            "DELETE FROM observer_memory_fts WHERE memory_id = ?", (memoryId,)
        )
        self._indexMemory(
            connection,
            memoryId,
            candidate["subjectKey"],
            candidate["summary"],
        )

    def _upsertSource(
        self, connection: sqlite3.Connection, normalizedEvent: dict[str, Any]
    ) -> str:
        """Resolve one stable provenance source without treating profiles as users."""
        sourceSeed = (
            f"browser:{normalizedEvent['browserFamily']}:{normalizedEvent['profileId']}"
        )
        sourceId = str(uuid5(NAMESPACE_URL, sourceSeed))
        occurredAt = normalizedEvent["occurredAt"].isoformat()
        connection.execute(
            """INSERT INTO observer_sources (
                   id, source_kind, browser_family, profile_id, profile_label,
                   first_seen_at, last_seen_at
               ) VALUES (?, 'BROWSER', ?, ?, ?, ?, ?)
               ON CONFLICT(source_kind, browser_family, profile_id) DO UPDATE SET
                   profile_label = COALESCE(excluded.profile_label, observer_sources.profile_label),
                   last_seen_at = excluded.last_seen_at""",
            (
                sourceId,
                normalizedEvent["browserFamily"],
                normalizedEvent["profileId"],
                normalizedEvent["profileLabel"],
                occurredAt,
                occurredAt,
            ),
        )
        return sourceId

    def _getOrCreateSession(
        self, connection: sqlite3.Connection, sourceId: str, occurredAt: datetime
    ) -> str:
        """Reuse a recent open session or create an independent activity session."""
        sessionRow = connection.execute(
            """SELECT id, last_event_at FROM observer_sessions
               WHERE source_id = ? AND status = 'OPEN'
               ORDER BY last_event_at DESC LIMIT 1""",
            (sourceId,),
        ).fetchone()
        if sessionRow is not None:
            lastEventAt = datetime.fromisoformat(str(sessionRow[1]))
            if timedelta(0) <= occurredAt - lastEventAt <= timedelta(minutes=10):
                return str(sessionRow[0])
            connection.execute(
                """UPDATE observer_sessions
                   SET status = 'CLOSED', ended_at = last_event_at WHERE id = ?""",
                (sessionRow[0],),
            )
        sessionId = str(uuid4())
        connection.execute(
            """INSERT INTO observer_sessions (
                   id, source_id, started_at, last_event_at, status, event_count
               ) VALUES (?, ?, ?, ?, 'OPEN', 0)""",
            (sessionId, sourceId, occurredAt.isoformat(), occurredAt.isoformat()),
        )
        return sessionId

    def _normalizeUrl(self, rawUrl: str) -> tuple[str, str]:
        """Accept ordinary web URLs, strip tracking, and enforce default exclusions."""
        parsedUrl = urlsplit(rawUrl)
        if parsedUrl.scheme not in {"http", "https"} or not parsedUrl.hostname:
            raise ValueError("Observer accepts only HTTP or HTTPS URLs")
        domain = parsedUrl.hostname.lower().rstrip(".")
        if any(marker in domain for marker in SENSITIVE_HOST_MARKERS):
            raise PermissionError("Observer location is excluded by privacy policy")
        cleanQuery = [
            (name, value)
            for name, value in parse_qsl(parsedUrl.query, keep_blank_values=True)
            if name.lower() not in TRACKING_QUERY_NAMES
            and not name.lower().startswith(TRACKING_QUERY_PREFIXES)
        ]
        normalizedUrl = urlunsplit(
            (parsedUrl.scheme.lower(), parsedUrl.netloc.lower(), parsedUrl.path, urlencode(cleanQuery), "")
        )
        return normalizedUrl, domain

    def _redactText(self, value: str) -> str:
        """Redact common inline credential forms before any durable write."""
        return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value).strip()

    def _indexMemory(
        self, connection: sqlite3.Connection, memoryId: str, subjectKey: str, summary: str
    ) -> None:
        """Maintain the explicit FTS row inside the caller's transaction."""
        connection.execute(
            """INSERT INTO observer_memory_fts (memory_id, subject_key, summary)
               VALUES (?, ?, ?)""",
            (memoryId, subjectKey, summary),
        )

    def _serializeMemory(self, row: sqlite3.Row | tuple[object, ...]) -> dict[str, object]:
        """Map one stable database row into the local retrieval contract."""
        return {
            "id": str(row[0]),
            "memoryKind": str(row[1]),
            "trustLevel": str(row[2]),
            "subjectKey": str(row[3]),
            "summary": str(row[4]),
            "confidence": float(row[5]),
            "evidenceCount": int(row[6]),
            "independentSessionCount": int(row[7]),
            "isUncertain": bool(row[8]),
            "firstSeenAt": str(row[9]),
            "lastSeenAt": str(row[10]),
        }

    def _requireAwareTimestamp(self, timestamp: datetime) -> None:
        """Reject local-time ambiguity at the durable session boundary."""
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Observer timestamps must include a timezone")
