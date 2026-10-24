/** Persist local collector pairing settings without contacting any remote service. */

const settingsForm = document.getElementById("settings-form");
const profileLabelInput = document.getElementById("profile-label");
const observerTokenInput = document.getElementById("observer-token");
const isEnabledInput = document.getElementById("is-enabled");
const statusElement = document.getElementById("status");

/** Restore the current profile label and monitoring state. */
async function loadSettings() {
  try {
    const settings = await chrome.storage.local.get([
      "isEnabled",
      "observerToken",
      "profileLabel"
    ]);
    profileLabelInput.value = settings.profileLabel || "";
    observerTokenInput.value = settings.observerToken || "";
    isEnabledInput.checked = settings.isEnabled !== false;
  } catch (error) {
    statusElement.textContent = "Local settings could not be loaded.";
  }
}

/** Save an ingress-only token and user-editable provenance label locally. */
async function saveSettings(event) {
  event.preventDefault();
  const observerToken = observerTokenInput.value.trim();
  const profileLabel = profileLabelInput.value.trim();
  if (!observerToken) {
    statusElement.textContent = "A local ingress token is required.";
    return;
  }
  try {
    await chrome.storage.local.set({
      isEnabled: isEnabledInput.checked,
      observerToken,
      profileLabel
    });
    statusElement.textContent = "Saved locally.";
  } catch (error) {
    statusElement.textContent = "Local settings could not be saved.";
  }
}

settingsForm.addEventListener("submit", (event) => {
  void saveSettings(event);
});

void loadSettings();
