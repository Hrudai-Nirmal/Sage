/**
 * Collect permitted browser events and deliver them to Sage's loopback ingress.
 * Page content remains untrusted metadata and this worker has no action privileges.
 */

const OBSERVER_ENDPOINT = "http://127.0.0.1:8787/v1/observer/events";
const MAX_PAGE_TEXT_LENGTH = 12000;
const ACTIVE_PAGE_DELAY_MILLISECONDS = 5000;
const IDLE_THRESHOLD_SECONDS = 300;
const ACTIVE_ALARM_PREFIX = "sage-active-page-";
const DEFAULT_SETTINGS = {
  isEnabled: true,
  observerToken: "",
  profileId: "",
  profileLabel: ""
};
const HARD_DENY_HOST_MARKERS = [
  "1password",
  "authenticator",
  "bank",
  "bitwarden",
  "coinbase",
  "health",
  "mail.google.com",
  "paypal",
  "stripe"
];
const HARD_DENY_PATH_MARKERS = [
  "/login",
  "/signin",
  "/oauth",
  "/checkout",
  "/payment",
  "/password",
  "/credentials"
];

/** Initialize local identity and the Chromium idle detector. */
async function initializeObserver() {
  try {
    const settings = await getSettings();
    if (!settings.profileId) {
      await chrome.storage.local.set({profileId: crypto.randomUUID()});
    }
    chrome.idle.setDetectionInterval(IDLE_THRESHOLD_SECONDS);
    await updateBadge(settings.isEnabled && Boolean(settings.observerToken) ? "connected" : "paused");
  } catch (error) {
    await updateBadge("disconnected");
  }
}

/** Return validated extension-local settings without inventing a credential. */
async function getSettings() {
  try {
    const storedSettings = await chrome.storage.local.get(Object.keys(DEFAULT_SETTINGS));
    return {...DEFAULT_SETTINGS, ...storedSettings};
  } catch (error) {
    throw new Error("Observer settings are unavailable", {cause: error});
  }
}

/** Infer a display-only Chromium family for provenance. */
function getBrowserFamily() {
  const userAgent = navigator.userAgent;
  if (userAgent.includes("Edg/")) return "EDGE";
  if (userAgent.includes("Brave/")) return "BRAVE";
  if (userAgent.includes("Arc/")) return "ARC";
  if (userAgent.includes("Chromium/")) return "CHROMIUM";
  return "CHROME";
}

/** Reject sensitive and browser-internal locations before any event is assembled. */
function isPermittedUrl(rawUrl) {
  try {
    const pageUrl = new URL(rawUrl);
    if (!['http:', 'https:'].includes(pageUrl.protocol)) return false;
    const host = pageUrl.hostname.toLowerCase();
    const path = pageUrl.pathname.toLowerCase();
    return !HARD_DENY_HOST_MARKERS.some((marker) => host.includes(marker))
      && !HARD_DENY_PATH_MARKERS.some((marker) => path.includes(marker));
  } catch (error) {
    return false;
  }
}

/** Extract a Google search term from the URL without inspecting an input field. */
function getSearchQuery(rawUrl) {
  try {
    const pageUrl = new URL(rawUrl);
    if (!pageUrl.hostname.endsWith("google.com") || pageUrl.pathname !== "/search") return null;
    return (pageUrl.searchParams.get("q") || "").slice(0, 2000) || null;
  } catch (error) {
    return null;
  }
}

/** Submit one bounded observation with the ingress-only token. */
async function sendObserverEvent(eventPayload) {
  const settings = await getSettings();
  if (!settings.isEnabled || !settings.observerToken || !settings.profileId) {
    await updateBadge("paused");
    return;
  }
  try {
    const response = await fetch(OBSERVER_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Sage-Observer-Token": settings.observerToken
      },
      body: JSON.stringify({
        ...eventPayload,
        browserFamily: getBrowserFamily(),
        eventId: crypto.randomUUID(),
        occurredAt: new Date().toISOString(),
        profileId: settings.profileId,
        profileLabel: settings.profileLabel || undefined
      })
    });
    if (response.status === 409) {
      await updateBadge("paused");
      return;
    }
    if (!response.ok) throw new Error(`Observer ingress returned ${response.status}`);
    await updateBadge("connected");
  } catch (error) {
    await updateBadge("disconnected");
  }
}

/** Record a permitted navigation without waiting for page extraction. */
async function recordNavigation(details) {
  if (details.frameId !== 0 || !isPermittedUrl(details.url)) return;
  try {
    const tab = await chrome.tabs.get(details.tabId);
    await sendObserverEvent({
      eventType: getSearchQuery(details.url) ? "SEARCH" : "NAVIGATION",
      searchQuery: getSearchQuery(details.url) || undefined,
      title: (tab.title || "").slice(0, 2000) || undefined,
      url: details.url
    });
    await scheduleActivePage(details.tabId);
  } catch (error) {
    await updateBadge("disconnected");
  }
}

/** Debounce active-page extraction using an MV3-safe alarm. */
async function scheduleActivePage(tabId) {
  try {
    await chrome.alarms.create(`${ACTIVE_ALARM_PREFIX}${tabId}`, {
      when: Date.now() + ACTIVE_PAGE_DELAY_MILLISECONDS
    });
  } catch (error) {
    await updateBadge("disconnected");
  }
}

/** Request a bounded semantic extract from the active top-level page. */
async function recordActivePage(tabId) {
  try {
    const [activeTab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
    if (!activeTab || activeTab.id !== tabId || !activeTab.url || !isPermittedUrl(activeTab.url)) return;
    const pageExtract = await chrome.tabs.sendMessage(tabId, {type: "SAGE_OBSERVER_EXTRACT"});
    await sendObserverEvent({
      activeDurationSeconds: Math.max(30, Number(pageExtract.activeDurationSeconds || 0)),
      eventType: "ACTIVE_PAGE",
      pageText: String(pageExtract.pageText || "").slice(0, MAX_PAGE_TEXT_LENGTH) || undefined,
      searchQuery: getSearchQuery(activeTab.url) || undefined,
      title: (activeTab.title || "").slice(0, 2000) || undefined,
      url: activeTab.url
    });
  } catch (error) {
    await updateBadge("disconnected");
  }
}

/** Reflect monitoring state without exposing activity text. */
async function updateBadge(state) {
  const badgeByState = {
    connected: {color: "#30D158", text: "•"},
    disconnected: {color: "#8E8E93", text: "!"},
    paused: {color: "#FF9F0A", text: "II"}
  };
  const badge = badgeByState[state] || badgeByState.disconnected;
  try {
    await chrome.action.setBadgeBackgroundColor({color: badge.color});
    await chrome.action.setBadgeText({text: badge.text});
  } catch (error) {
    // A badge failure must not expand permissions or interrupt ordinary browsing.
  }
}

chrome.webNavigation.onCommitted.addListener((details) => {
  void recordNavigation(details);
});

chrome.tabs.onActivated.addListener(({tabId}) => {
  void scheduleActivePage(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) void scheduleActivePage(tabId);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm.name.startsWith(ACTIVE_ALARM_PREFIX)) return;
  const tabId = Number(alarm.name.slice(ACTIVE_ALARM_PREFIX.length));
  if (Number.isInteger(tabId)) void recordActivePage(tabId);
});

chrome.idle.onStateChanged.addListener((state) => {
  void sendObserverEvent({eventType: state === "active" ? "RESUME" : "IDLE"});
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "SAGE_OBSERVER_VIDEO_PROGRESS" || !sender.tab?.url) return;
  if (!isPermittedUrl(sender.tab.url)) return;
  void sendObserverEvent({
    activeDurationSeconds: message.video.progressSeconds,
    eventType: "VIDEO_PROGRESS",
    title: (sender.tab.title || "").slice(0, 2000) || undefined,
    url: sender.tab.url,
    video: message.video
  });
});

void initializeObserver();
