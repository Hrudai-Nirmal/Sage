"""Coordinate one durable Observer session with the existing Iris classifier."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from sage_core.observer.state import ObserverStateRepository


class ObserverAnalyzer(Protocol):
    """Define the only structured capability Iris exposes to Observer."""

    def analyzeSession(self, session: dict[str, object]) -> dict[str, object]:
        """Return schema-bound analysis for one claimed session."""


class ObserverProcessingService:
    """Claim, analyze, and complete at most one durable Observer session."""

    def __init__(
        self,
        observerStateRepository: ObserverStateRepository,
        observerAnalyzer: ObserverAnalyzer,
    ) -> None:
        """Inject state and Iris boundaries so retries remain deterministic."""
        self.observerStateRepository = observerStateRepository
        self.observerAnalyzer = observerAnalyzer

    def processNextSession(self, now: datetime) -> dict[str, str]:
        """Process one queue item or return a truthful idle/retry receipt."""
        self.observerStateRepository.closeInactiveSessions(now)
        claimedSession = self.observerStateRepository.claimPendingSession(now)
        if claimedSession is None:
            return {"status": "IDLE"}
        sessionId = str(claimedSession["sessionId"])
        try:
            analysis = self.observerAnalyzer.analyzeSession(claimedSession)
            self.observerStateRepository.applySessionAnalysis(sessionId, analysis)
            return {"status": "COMPLETE", "sessionId": sessionId}
        except Exception as error:
            self.observerStateRepository.releaseSessionAfterFailure(
                sessionId,
                type(error).__name__,
                now + timedelta(minutes=5),
            )
            return {"status": "RETRY", "sessionId": sessionId}
