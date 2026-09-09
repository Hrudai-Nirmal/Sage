"""Provide bounded public-web retrieval with durable citations and audit evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import uuid4

from sage_core.audit_state import AuditStateRepository
from sage_core.database import SageDatabase


SearchRequest = Callable[[str, dict[str, object], dict[str, str]], dict[str, object]]
PageExtractor = Callable[[str], str | None]


def validatePublicUrl(url: str, resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo) -> None:
    """Reject malformed, non-HTTP, local, and non-public network destinations."""
    parsedUrl = urlparse(url)
    if parsedUrl.scheme not in {"http", "https"} or not parsedUrl.hostname:
        raise PermissionError("Research URLs must use public HTTP or HTTPS")
    if parsedUrl.username or parsedUrl.password:
        raise PermissionError("Research URLs may not contain credentials")
    try:
        defaultPort = 443 if parsedUrl.scheme == "https" else 80
        addresses = resolver(parsedUrl.hostname, parsedUrl.port or defaultPort)
    except socket.gaierror as error:
        raise ConnectionError("Research hostname could not be resolved") from error
    for address in addresses:
        ipValue = ipaddress.ip_address(address[4][0])
        if not ipValue.is_global:
            raise PermissionError("Research URLs may not target private networks")


class _PublicRedirectHandler(HTTPRedirectHandler):
    """Revalidate every redirect target before urllib follows it."""

    def redirect_request(self, request, filePointer, code, message, headers, newUrl):
        """Permit a redirect only when its destination remains public."""
        validatePublicUrl(newUrl)
        return super().redirect_request(request, filePointer, code, message, headers, newUrl)


def extractPublicPage(url: str, maxBytes: int = 2_000_000) -> str | None:
    """Fetch and extract one public HTML page with strict time and size bounds."""
    validatePublicUrl(url)
    request = Request(url, headers={"User-Agent": "SageResearch/0.1 (+local personal assistant)"})
    with build_opener(_PublicRedirectHandler()).open(request, timeout=15) as response:
        contentType = response.headers.get_content_type()
        if contentType not in {"text/html", "text/plain", "application/xhtml+xml"}:
            return None
        pageBytes = response.read(maxBytes + 1)
        if len(pageBytes) > maxBytes:
            raise ValueError("Research page exceeds the extraction limit")
        charset = response.headers.get_content_charset() or "utf-8"
    pageText = pageBytes.decode(charset, errors="replace")
    if contentType == "text/plain":
        return pageText[:30_000]
    from trafilatura import extract

    return extract(
        pageText,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_links=True,
    )


def _postJson(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    """Post JSON to an external API without exposing authorization values."""
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


class OnlineResearchService:
    """Search Tavily, extract public sources locally, and retain a bounded evidence record."""

    def __init__(
        self,
        database: SageDatabase,
        tavilyApiKey: str,
        searchRequest: SearchRequest = _postJson,
        pageExtractor: PageExtractor = extractPublicPage,
    ) -> None:
        """Configure the private provider credential and injectable network boundaries."""
        if not tavilyApiKey.strip():
            raise ValueError("tavilyApiKey is required")
        self.database = database
        self.tavilyApiKey = tavilyApiKey
        self.searchRequest = searchRequest
        self.pageExtractor = pageExtractor
        self.auditStateRepository = AuditStateRepository(database)

    def searchWeb(self, query: str, maxResults: int = 3) -> dict[str, object]:
        """Retrieve and persist up to five citation-ready public sources."""
        normalizedQuery = query.strip()
        if not normalizedQuery:
            raise ValueError("Research query is required")
        if maxResults < 1 or maxResults > 5:
            raise ValueError("maxResults must be between 1 and 5")
        providerResponse = self.searchRequest(
            "https://api.tavily.com/search",
            {
                "query": normalizedQuery,
                "country": "india",
                "search_depth": "basic",
                "max_results": maxResults,
                "include_answer": False,
                "include_raw_content": False,
            },
            {
                "Authorization": f"Bearer {self.tavilyApiKey}",
                "Content-Type": "application/json",
            },
        )
        sources: list[dict[str, str]] = []
        for rawSource in list(providerResponse.get("results", []))[:maxResults]:
            if not isinstance(rawSource, dict):
                continue
            sourceUrl = str(rawSource.get("url", ""))
            try:
                extractedContent = self.pageExtractor(sourceUrl)
            except (ConnectionError, OSError, PermissionError, ValueError):
                extractedContent = None
            sourceContent = (extractedContent or str(rawSource.get("content", "")))[:30_000]
            if sourceUrl and sourceContent:
                sources.append(
                    {
                        "title": str(rawSource.get("title", sourceUrl))[:500],
                        "url": sourceUrl,
                        "content": sourceContent,
                    }
                )
        researchId = str(uuid4())
        retrievedAt = datetime.now(UTC).isoformat()
        with self.database.connectDatabase() as connection:
            connection.execute(
                "INSERT INTO research_runs (id, query, retrieved_at, sources_json) VALUES (?, ?, ?, ?)",
                (researchId, normalizedQuery, retrievedAt, json.dumps(sources)),
            )
            self.auditStateRepository.recordEvent(
                connection=connection,
                actor="sage:research",
                actionType="SEARCH_WEB",
                targetType="RESEARCH_RUN",
                targetId=researchId,
                eventStatus="COMPLETE",
                metadata={"sourceCount": str(len(sources))},
            )
        return {
            "id": researchId,
            "query": normalizedQuery,
            "retrievedAt": retrievedAt,
            "sources": sources,
        }
