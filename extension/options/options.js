import { MSG, callBackground } from "../shared/messages.js";
import { getSettings, saveSettings } from "../shared/settings.js";

const $ = (id) => document.getElementById(id);
const CHECKBOXES = ["showOverlayButton", "useCookies", "useCookiesForYouTube"];

let savedTimer;
function flashSaved() {
  $("saved").textContent = "Saved";
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { $("saved").textContent = ""; }, 1500);
}

async function save(partial) {
  await saveSettings(partial);
  flashSaved();
}

function syncDependentControls() {
  $("useCookiesForYouTube").disabled = !$("useCookies").checked;
}

async function loadHelper() {
  try {
    const info = await callBackground(MSG.HELPER_STATUS);
    $("helper-line").textContent = `Connected · yt-dlp ${info.ytdlp_version}`;
    const tools = [`ffmpeg ${info.ffmpeg ? "✓" : "✗ missing"}`, `deno ${info.deno ? "✓" : "✗ missing (needed for YouTube)"}`];
    $("helper-detail").textContent = `Helper ${info.helper_version} · Python ${info.python} · ${tools.join(" · ")}`;
  } catch (error) {
    $("helper-line").textContent = "Helper not connected";
    $("helper-detail").textContent = error.message;
    $("update-btn").disabled = true;
  }
}

async function init() {
  const settings = await getSettings();

  // Keep toggles in sync when a setting is changed elsewhere (e.g. from the panel).
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "sync") return;
    for (const id of CHECKBOXES) {
      if (id in changes) $(id).checked = changes[id].newValue !== false;
    }
    syncDependentControls();
  });

  $("downloadDir").value = settings.downloadDir;
  $("downloadDir").addEventListener("change", (e) => save({ downloadDir: e.target.value.trim() }));

  for (const id of CHECKBOXES) {
    $(id).checked = Boolean(settings[id]);
    $(id).addEventListener("change", (e) => {
      syncDependentControls();
      save({ [id]: e.target.checked });
    });
  }
  syncDependentControls();

  $("update-btn").addEventListener("click", async () => {
    const button = $("update-btn");
    button.disabled = true;
    button.textContent = "Updating…";
    try {
      const result = await callBackground(MSG.UPDATE_YTDLP);
      button.textContent = result.restart_required ? `Updated to ${result.ytdlp_version}` : "Already up to date";
    } catch (error) {
      button.textContent = "Update failed";
      $("helper-detail").textContent = error.message;
    }
  });

  setupUpdates(settings);
  loadHelper();
}

// -- VidGrab updates ----------------------------------------------------------

function setupUpdates(settings) {
  const select = $("updateCheckDays");
  select.value = String(settings.updateCheckDays);
  select.addEventListener("change", () => save({ updateCheckDays: Number(select.value) }));

  const button = $("check-update-btn");
  const detail = $("version-detail");
  let pending = null; // status of an available update, once found

  const show = (status) => {
    $("version-line").textContent = `VidGrab ${status.current}`;
    if (status.available) {
      pending = status;
      detail.textContent = `${status.latest} available`;
      button.textContent = "Update";
      button.classList.replace("secondary", "primary");
    } else {
      detail.textContent = status.checked ? "Up to date" : "";
    }
  };

  $("version-line").textContent = `VidGrab ${chrome.runtime.getManifest().version}`;
  callBackground(MSG.CHECK_UPDATE).then(show).catch(() => {});

  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      if (pending) {
        button.textContent = "Updating…";
        const result = await callBackground(MSG.APPLY_UPDATE);
        detail.textContent = `Updated to ${result.version}`;
        return; // the extension reloads itself and this page closes
      }
      button.textContent = "Checking…";
      show(await callBackground(MSG.CHECK_UPDATE, { force: true }));
      if (!pending) button.textContent = "Check for updates";
    } catch (error) {
      detail.textContent = error.message;
      button.textContent = pending ? "Update" : "Check for updates";
    }
    button.disabled = false;
  });
}

init();
