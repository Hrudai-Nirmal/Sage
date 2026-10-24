"""Test the static privacy and runtime contract of the Chromium collector."""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = PROJECT_ROOT / "browser-extension" / "sage-observer"


def testManifestUsesStableMv3IdentityAndRejectsIncognito():
    """Every Chromium profile gets one stable, private-mode-disabled collector."""
    manifest = json.loads((EXTENSION_ROOT / "manifest.json").read_text())

    assert manifest["manifest_version"] == 3
    assert manifest["incognito"] == "not_allowed"
    assert manifest["key"]
    assert manifest["background"] == {"service_worker": "background.js", "type": "module"}
    assert "<all_urls>" in manifest["host_permissions"]
    assert "http://127.0.0.1:8787/*" in manifest["host_permissions"]
    assert set(manifest["permissions"]) == {"alarms", "idle", "storage", "tabs", "webNavigation"}


def testManifestDoesNotRequestHighRiskBrowserCapabilities():
    """The collector has no route to input values, files, history, or page execution."""
    manifestText = (EXTENSION_ROOT / "manifest.json").read_text().lower()

    for forbiddenPermission in (
        "clipboardread",
        "clipboardwrite",
        "debugger",
        "downloads",
        "history",
        "nativeMessaging".lower(),
        "scripting",
    ):
        assert forbiddenPermission not in manifestText
    manifest = json.loads(manifestText)
    assert manifest["content_scripts"][0]["all_frames"] is False
    assert manifest["content_scripts"][0]["match_about_blank"] is False


def testBackgroundWorkerBoundsEventsAndExposesNoDefaultCredential():
    """The worker collects metadata only after local pairing and applies fixed bounds."""
    workerText = (EXTENSION_ROOT / "background.js").read_text()

    assert "MAX_PAGE_TEXT_LENGTH = 12000" in workerText
    assert "ACTIVE_PAGE_DELAY_MILLISECONDS = 5000" in workerText
    assert "http://127.0.0.1:8787/v1/observer/events" in workerText
    assert "observerToken: \"\"" in workerText
    assert "chrome.webNavigation.onCommitted" in workerText
    assert "chrome.tabs.onActivated" in workerText
    assert "chrome.idle.onStateChanged" in workerText
    assert "document.querySelector" not in workerText
    assert "executeScript" not in workerText


def testOptionsPageStoresProfileAndIngressTokenWithoutRemoteServices():
    """Pairing settings remain inside extension-local storage and use no analytics."""
    optionsText = (EXTENSION_ROOT / "options.js").read_text()

    assert "chrome.storage.local.set" in optionsText
    assert "profileLabel" in optionsText
    assert "observerToken" in optionsText
    assert "fetch(" not in optionsText
