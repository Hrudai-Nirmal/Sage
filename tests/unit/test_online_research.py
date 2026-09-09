"""Unit tests for Sage's bounded and SSRF-safe online research boundary."""

from pathlib import Path
import sqlite3

import pytest

from sage_core.database import SageDatabase
from sage_core.online_research import OnlineResearchService, validatePublicUrl


def testRejectsPrivateAndNonHttpResearchUrls():
    """Online tools must never become a path into localhost or private networks."""
    privateResolver = lambda host, port: [(None, None, None, None, ("127.0.0.1", port))]

    with pytest.raises(PermissionError):
        validatePublicUrl("http://localhost/private", resolver=privateResolver)
    with pytest.raises(PermissionError):
        validatePublicUrl("file:///etc/passwd")


def testSearchPersistsBoundedSourcesAndAuditEvent(tmp_path):
    """A successful search retains citations and an auditable retrieval timestamp."""
    database = SageDatabase(tmp_path / "sage.db")

    def fakeSearchRequest(url, payload, headers):
        assert payload["search_depth"] == "basic"
        assert payload["max_results"] == 2
        assert payload["country"] == "india"
        return {
            "request_id": "request-1",
            "results": [
                {"title": "One", "url": "https://one.example/a", "content": "snippet one"},
                {"title": "Two", "url": "https://two.example/b", "content": "snippet two"},
            ],
        }

    service = OnlineResearchService(
        database=database,
        tavilyApiKey="private-key",
        searchRequest=fakeSearchRequest,
        pageExtractor=lambda url: f"full text from {url}",
    )

    research = service.searchWeb("current topic", maxResults=2)

    assert research["query"] == "current topic"
    assert len(research["sources"]) == 2
    assert research["sources"][0]["url"] == "https://one.example/a"
    assert research["sources"][0]["content"].startswith("full text")
    assert research["retrievedAt"]
    with sqlite3.connect(tmp_path / "sage.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 1
        assert connection.execute(
            "SELECT action_type, status FROM audit_events WHERE target_type = 'RESEARCH_RUN'"
        ).fetchone() == ("SEARCH_WEB", "COMPLETE")
