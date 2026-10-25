"""Test the authenticated Observer loopback API boundary."""

from fastapi.testclient import TestClient

from sage_core.app import createApp


def buildIngressEvent() -> dict[str, object]:
    """Build one valid extension event without sensitive browser content."""
    return {
        "activeDurationSeconds": 30,
        "browserFamily": "BRAVE",
        "eventId": "7bd44f84-9dc7-45f3-a4c9-94efc8e6f64f",
        "eventType": "ACTIVE_PAGE",
        "occurredAt": "2026-10-25T09:00:00+05:30",
        "pageText": "A bounded article extract.",
        "profileId": "profile-default",
        "profileLabel": "Personal",
        "title": "Dive watch guide",
        "url": "https://example.com/watches?utm_campaign=fall",
    }


def buildDesktopIngressEvent() -> dict[str, object]:
    """Build one valid native application event without captured screen content."""
    return {
        "activeDurationSeconds": 30,
        "appBundleId": "com.microsoft.VSCode",
        "appName": "Visual Studio Code",
        "eventId": "desktop-event-1",
        "eventType": "WINDOW_CHANGED",
        "hostId": "hrudais-macbook-pro",
        "occurredAt": "2026-10-25T09:00:00+05:30",
        "windowTitle": "observer-state.py — Sage",
    }


def testAuthenticatesOriginAndDeduplicatesExtensionEvents(tmp_path):
    """An ingress-only token and exact extension Origin protect the write endpoint."""
    allowedOrigin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    app = createApp(
        databasePath=tmp_path / "sage.db",
        observerAllowedOrigins={allowedOrigin},
        observerIngressToken="observer-token",
    )
    headers = {
        "Origin": allowedOrigin,
        "X-Sage-Observer-Token": "observer-token",
    }

    with TestClient(app) as client:
        preflight = client.options(
            "/v1/observer/events",
            headers={
                "Access-Control-Request-Headers": "content-type,x-sage-observer-token",
                "Access-Control-Request-Method": "POST",
                "Origin": allowedOrigin,
            },
        )
        missingToken = client.post(
            "/v1/observer/events",
            json=buildIngressEvent(),
            headers={"Origin": allowedOrigin},
        )
        wrongOrigin = client.post(
            "/v1/observer/events",
            json=buildIngressEvent(),
            headers={
                "Origin": "chrome-extension://wrong",
                "X-Sage-Observer-Token": "observer-token",
            },
        )
        accepted = client.post("/v1/observer/events", json=buildIngressEvent(), headers=headers)
        duplicate = client.post("/v1/observer/events", json=buildIngressEvent(), headers=headers)

    assert missingToken.status_code == 422
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == allowedOrigin
    assert wrongOrigin.status_code == 403
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "ACCEPTED"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "DUPLICATE"


def testCorsPreflightRejectsUnlistedExtensionOrigin(tmp_path):
    """The browser bridge never reflects an arbitrary extension Origin."""
    allowedOrigin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    app = createApp(
        databasePath=tmp_path / "sage.db",
        observerAllowedOrigins={allowedOrigin},
        observerIngressToken="observer-token",
    )

    with TestClient(app) as client:
        response = client.options(
            "/v1/observer/events",
            headers={
                "Access-Control-Request-Headers": "content-type,x-sage-observer-token",
                "Access-Control-Request-Method": "POST",
                "Origin": "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def testRejectsOversizedOrDurableCaptionPayloads(tmp_path):
    """The durable ingress has no caption field and bounds cleaned page extracts."""
    allowedOrigin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    app = createApp(
        databasePath=tmp_path / "sage.db",
        observerAllowedOrigins={allowedOrigin},
        observerIngressToken="observer-token",
    )
    headers = {
        "Origin": allowedOrigin,
        "X-Sage-Observer-Token": "observer-token",
    }
    oversizedEvent = buildIngressEvent() | {"pageText": "a" * 12_001}
    captionEvent = buildIngressEvent() | {"captions": "Never persist me"}

    with TestClient(app) as client:
        oversized = client.post("/v1/observer/events", json=oversizedEvent, headers=headers)
        captions = client.post("/v1/observer/events", json=captionEvent, headers=headers)

    assert oversized.status_code == 422
    assert captions.status_code == 422


def testSearchesObserverMemoriesWithBoundedResultLimit(tmp_path):
    """The local retrieval API validates result bounds even before memories exist."""
    app = createApp(databasePath=tmp_path / "sage.db")

    with TestClient(app) as client:
        response = client.get("/v1/observer/memories", params={"query": "watch", "resultLimit": 13})
        invalid = client.get("/v1/observer/memories", params={"resultLimit": 101})

    assert response.status_code == 200
    assert response.json() == []
    assert invalid.status_code == 422


def testObserverControlPersistsAndBlocksCollectionInOffOrSleepState(tmp_path):
    """Core, not the extension, enforces user and runtime collection controls."""
    allowedOrigin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    databasePath = tmp_path / "sage.db"
    app = createApp(
        databasePath=databasePath,
        observerAllowedOrigins={allowedOrigin},
        observerIngressToken="observer-token",
        operatorToken="operator-token",
    )
    ingressHeaders = {
        "Origin": allowedOrigin,
        "X-Sage-Observer-Token": "observer-token",
    }
    operatorHeaders = {"X-Sage-Operator-Token": "operator-token"}

    with TestClient(app) as client:
        initialStatus = client.get("/v1/observer/status")
        turnedOff = client.patch(
            "/v1/observer/status",
            json={"monitoringState": "OFF"},
            headers=operatorHeaders,
        )
        blockedWhileOff = client.post(
            "/v1/observer/events", json=buildIngressEvent(), headers=ingressHeaders
        )

    restartedApp = createApp(
        databasePath=databasePath,
        observerAllowedOrigins={allowedOrigin},
        observerIngressToken="observer-token",
        operatorToken="operator-token",
    )
    with TestClient(restartedApp) as client:
        persistedStatus = client.get("/v1/observer/status")
        client.patch(
            "/v1/observer/status",
            json={"monitoringState": "ON"},
            headers=operatorHeaders,
        )
        client.patch(
            "/v1/system/mode",
            json={"mode": "SLEEP"},
            headers=operatorHeaders,
        )
        blockedWhileSleeping = client.post(
            "/v1/observer/events", json=buildIngressEvent(), headers=ingressHeaders
        )

    assert initialStatus.json()["monitoringState"] == "ON"
    assert initialStatus.json()["isCollecting"] is True
    assert turnedOff.json()["monitoringState"] == "OFF"
    assert blockedWhileOff.status_code == 409
    assert persistedStatus.json()["monitoringState"] == "OFF"
    assert blockedWhileSleeping.status_code == 409


def testExpiredObserverPauseResumesAutomatically(tmp_path):
    """A bounded pause returns to monitoring without a second manual action."""
    app = createApp(databasePath=tmp_path / "sage.db", operatorToken="operator-token")

    with TestClient(app) as client:
        paused = client.patch(
            "/v1/observer/status",
            json={
                "monitoringState": "PAUSED",
                "pauseUntil": "2020-01-01T00:00:00+00:00",
            },
            headers={"X-Sage-Operator-Token": "operator-token"},
        )
        current = client.get("/v1/observer/status")

    assert paused.json()["monitoringState"] == "ON"
    assert current.json()["isCollecting"] is True


def testDesktopIngressUsesIndependentTokenAndRuntimeGate(tmp_path):
    """The native observer cannot reuse browser or operator credentials for collection."""
    app = createApp(
        databasePath=tmp_path / "sage.db",
        nativeObserverToken="native-observer-token",
        observerIngressToken="browser-observer-token",
        operatorToken="operator-token",
    )

    with TestClient(app) as client:
        wrongToken = client.post(
            "/v1/observer/desktop-events",
            json=buildDesktopIngressEvent(),
            headers={"X-Sage-Native-Observer-Token": "browser-observer-token"},
        )
        accepted = client.post(
            "/v1/observer/desktop-events",
            json=buildDesktopIngressEvent(),
            headers={"X-Sage-Native-Observer-Token": "native-observer-token"},
        )
        client.patch(
            "/v1/system/mode",
            json={"mode": "SLEEP"},
            headers={"X-Sage-Operator-Token": "operator-token"},
        )
        blockedWhileSleeping = client.post(
            "/v1/observer/desktop-events",
            json=buildDesktopIngressEvent() | {"eventId": "desktop-event-2"},
            headers={"X-Sage-Native-Observer-Token": "native-observer-token"},
        )

    assert wrongToken.status_code == 403
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "ACCEPTED"
    assert blockedWhileSleeping.status_code == 409
