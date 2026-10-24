/**
 * Produce a bounded visible-text extract without reading inputs or retaining captions.
 */

const MAX_EXTRACT_LENGTH = 12000;
const EXCLUDED_ELEMENT_SELECTOR = [
  "script",
  "style",
  "noscript",
  "nav",
  "footer",
  "aside",
  "form",
  "input",
  "textarea",
  "select",
  "button",
  "[contenteditable='true']",
  "[role='navigation']",
  "[role='dialog']",
  "[aria-label*='password' i]",
  "[aria-label*='payment' i]",
  "[class*='advert' i]"
].join(",");
const pageActivatedAt = Date.now();
let hasReportedQualifyingVideo = false;

/** Return visible semantic text while skipping interactive and repetitive regions. */
function getBoundedPageText() {
  const semanticRoots = document.querySelectorAll("main, article, [role='main']");
  const roots = semanticRoots.length > 0 ? [...semanticRoots] : [document.body];
  const textParts = [];
  let currentLength = 0;
  for (const root of roots) {
    const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let textNode = textWalker.nextNode();
    while (textNode && currentLength < MAX_EXTRACT_LENGTH) {
      const parentElement = textNode.parentElement;
      if (parentElement && !parentElement.closest(EXCLUDED_ELEMENT_SELECTOR)) {
        const normalizedText = (textNode.textContent || "").replace(/\s+/g, " ").trim();
        if (normalizedText.length >= 20) {
          const boundedText = normalizedText.slice(0, MAX_EXTRACT_LENGTH - currentLength);
          textParts.push(boundedText);
          currentLength += boundedText.length + 1;
        }
      }
      textNode = textWalker.nextNode();
    }
    if (currentLength >= MAX_EXTRACT_LENGTH) break;
  }
  return textParts.join("\n").slice(0, MAX_EXTRACT_LENGTH);
}

/** Return visible YouTube metadata without collecting captions or comments. */
function getYouTubeVideoMetadata() {
  if (location.hostname !== "www.youtube.com" || location.pathname !== "/watch") return null;
  const videoElement = document.querySelector("video");
  const videoId = new URL(location.href).searchParams.get("v");
  if (!videoElement || !videoId || !Number.isFinite(videoElement.duration)) return null;
  return {
    channel: (document.querySelector("#channel-name")?.textContent || "").trim().slice(0, 500) || undefined,
    descriptionExcerpt: (document.querySelector("#description-inline-expander")?.textContent || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 2000) || undefined,
    durationSeconds: Math.round(videoElement.duration),
    progressSeconds: Math.round(videoElement.currentTime),
    videoId
  };
}

/** Report once when a non-short YouTube video reaches the chosen 50% evidence threshold. */
function reportQualifyingVideoProgress() {
  if (hasReportedQualifyingVideo) return;
  const videoMetadata = getYouTubeVideoMetadata();
  if (!videoMetadata || videoMetadata.durationSeconds <= 0) return;
  if (videoMetadata.progressSeconds / videoMetadata.durationSeconds < 0.5) return;
  hasReportedQualifyingVideo = true;
  try {
    chrome.runtime.sendMessage({
      type: "SAGE_OBSERVER_VIDEO_PROGRESS",
      video: videoMetadata
    });
  } catch (error) {
    hasReportedQualifyingVideo = false;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "SAGE_OBSERVER_EXTRACT") return false;
  sendResponse({
    activeDurationSeconds: Math.floor((Date.now() - pageActivatedAt) / 1000),
    pageText: getBoundedPageText()
  });
  return false;
});

if (location.hostname === "www.youtube.com" && location.pathname === "/watch") {
  window.setInterval(reportQualifyingVideoProgress, 5000);
}
