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

  loadHelper();
}

init();
