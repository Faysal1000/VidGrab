// Popup / in-page panel UI.
//
// Opened three ways:
//   - toolbar button           -> finds the active video in the current tab
//   - in-page panel (iframe)   -> ?embedded=1&url=...&direct=...
//   - fallback tab             -> ?tab=1&url=...

import { MSG, JOBS_STORAGE_KEY, JOB_STATUS, ACTIVE_STATUSES, callBackground } from "../shared/messages.js";
import { getSettings, saveSettings } from "../shared/settings.js";
import { formatBytes, formatDuration, fileName } from "../shared/format.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const embedded = params.get("embedded") === "1";

const CONTAINER_LABELS = { mp4: "MP4", mkv: "MKV", webm: "WebM" };
const AUDIO_LABELS = { mp3: "MP3", m4a: "M4A (AAC)", wav: "WAV (lossless)" };
// Without a remembered choice, default to 1080p: "best" is often 4K, which
// is several times larger and slower to download.
const DEFAULT_QUALITY = 1080;

const STEP_LABELS = {
  Merger: "Merging video + audio…",
  VideoRemuxer: "Finalising file…",
  ExtractAudio: "Converting audio…",
  Metadata: "Adding metadata…",
  MoveFiles: "Saving…",
};

const state = {
  target: null, // { urls: string[], page: string }
  info: null,
  settings: null,
  kind: "video",
};

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

function showView(name) {
  for (const view of ["loading", "error", "video"]) $(`view-${view}`).hidden = view !== name;
}

function showError(message, { code } = {}) {
  const missing = code === "HELPER_MISSING";
  $("error-title").textContent = missing ? "Finish setting up VidGrab" : "Couldn't load this video";
  $("error-message").textContent = message;
  $("error-setup").hidden = !missing;
  showView("error");
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c != null));
  return node;
}

function fillSelect(select, options, selected) {
  select.replaceChildren(...options.map(({ value, label }) => el("option", { value, textContent: label })));
  if (options.some((o) => o.value === selected)) select.value = selected;
}

// ---------------------------------------------------------------------------
// Target detection
// ---------------------------------------------------------------------------

async function detectTarget() {
  if (params.get("url")) {
    return {
      urls: [params.get("url"), params.get("direct"), params.get("page")],
      page: params.get("page") || params.get("url"),
    };
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/.test(tab.url)) {
    throw new Error("Open a page with a video (YouTube, Instagram, Facebook, …) and try again.");
  }
  try {
    const found = await chrome.tabs.sendMessage(tab.id, { type: MSG.RESOLVE_ACTIVE_VIDEO });
    if (found?.url) return { urls: [found.url, found.direct, found.page], page: found.page };
  } catch {
    // Content script not present (tab opened before install) — use the tab URL.
  }
  return { urls: [tab.url], page: tab.url };
}

// ---------------------------------------------------------------------------
// Video card
// ---------------------------------------------------------------------------

function renderInfo(info) {
  if (!info.video.available && !info.audio.available) {
    showError("No downloadable video or audio was found on this page.");
    return;
  }
  const thumb = $("thumb");
  const media = thumb.closest(".media");
  media.hidden = !info.thumbnail;
  if (info.thumbnail) {
    thumb.src = info.thumbnail;
    // Some CDNs (e.g. Instagram) refuse hot-linking; just hide the image.
    thumb.onerror = () => { media.hidden = true; };
  }
  $("duration").hidden = !info.duration;
  $("duration").textContent = formatDuration(info.duration);
  $("title").textContent = info.title;
  const extras = [info.uploader, info.extractor];
  $("subtitle").textContent = extras.filter(Boolean).join(" · ");

  const { settings } = state;
  const qualities = [
    {
      value: "best",
      label: info.video.qualities.length ? `Best (${info.video.qualities[0].height}p)` : "Best available",
    },
    ...info.video.qualities.map(({ height, size }) => ({
      value: String(height),
      label: `${height}p${size ? ` · ~${formatBytes(size)}` : ""}`,
    })),
  ];
  fillSelect($("quality"), qualities, pickQuality(info.video.qualities, settings.lastQuality));
  fillSelect($("container"),
    info.video.containers.map((c) => ({ value: c, label: CONTAINER_LABELS[c] || c.toUpperCase() })),
    settings.lastContainer);
  fillSelect($("audio-format"),
    info.audio.formats.map((f) => ({ value: f, label: AUDIO_LABELS[f] || f.toUpperCase() })),
    settings.lastAudioFormat);

  const segVideo = document.querySelector('[data-kind="video"]');
  const segAudio = document.querySelector('[data-kind="audio"]');
  segVideo.disabled = !info.video.available;
  segAudio.disabled = !info.audio.available;
  const preferred = settings.lastKind === "audio" && info.audio.available ? "audio" : "video";
  setKind(info.video.available ? preferred : "audio");
  renderPlaylist(info.playlist);
  showView("video");
}

function renderPlaylist(playlist) {
  $("playlist-row").hidden = !playlist;
  if (!playlist) return;
  $("playlist-title").textContent = playlist.title;
  $("playlist-title").title = playlist.title;
  $("playlist-count").textContent = playlist.count ? `${playlist.count} videos` : "";
  $("playlist-btn").textContent = playlist.count ? `Download all ${playlist.count}` : "Download all";
}

/**
 * Use the remembered quality if this video has it; otherwise the highest one
 * at or below it (e.g. remembered 1080p but the video tops out at 720p).
 */
function pickQuality(qualities, remembered) {
  if (remembered === "best") return "best";
  const limit = Number(remembered) || DEFAULT_QUALITY;
  const match = qualities.find(({ height }) => height <= limit) ?? qualities.at(-1);
  return match ? String(match.height) : "best";
}

function setKind(kind) {
  state.kind = kind;
  for (const button of document.querySelectorAll(".segmented button")) {
    button.setAttribute("aria-selected", String(button.dataset.kind === kind));
  }
  $("video-options").hidden = kind !== "video";
  $("audio-options").hidden = kind !== "audio";
}

function currentChoice() {
  if (state.kind === "audio") return { kind: "audio", format: $("audio-format").value };
  const quality = $("quality").value;
  return {
    kind: "video",
    quality: quality === "best" ? null : Number(quality),
    container: $("container").value,
  };
}

async function loadInfo() {
  showView("loading");
  try {
    state.target ??= await detectTarget();
    state.info = await callBackground(MSG.GET_INFO, { urls: state.target.urls });
    renderInfo(state.info);
  } catch (error) {
    showError(error.message, error);
  }
}

const LARGE_PLAYLIST = 25;

/** @param {{playlist?: boolean}} [options] playlist: download the whole playlist */
async function startDownload({ playlist = false } = {}) {
  const button = $(playlist ? "playlist-btn" : "download-btn");
  const list = state.info.playlist;
  if (playlist && list?.count > LARGE_PLAYLIST
      && !confirm(`Download all ${list.count} videos? This can take a long time and use a lot of disk space.`)) {
    return;
  }
  button.disabled = true;
  const choice = { ...currentChoice(), ...(playlist ? { playlist: true } : {}) };
  try {
    await callBackground(MSG.START_DOWNLOAD, {
      url: playlist ? list.url : state.info.source_url,
      choice,
      meta: playlist
        ? { title: list.title, thumbnail: state.info.thumbnail }
        : { title: state.info.title, thumbnail: state.info.thumbnail },
    });
    saveSettings({
      lastKind: choice.kind,
      lastQuality: $("quality").value,
      lastContainer: $("container").value,
      lastAudioFormat: $("audio-format").value,
    });
  } catch (error) {
    showError(error.message, error);
  } finally {
    setTimeout(() => { button.disabled = false; }, 600);
  }
}

// ---------------------------------------------------------------------------
// Downloads list (live from chrome.storage.session)
// ---------------------------------------------------------------------------

function jobStatusText(job) {
  switch (job.status) {
    case JOB_STATUS.QUEUED:
      return "Starting…";
    case JOB_STATUS.DOWNLOADING: {
      // Playlists show which video they're on; single videos show which
      // stream (picture or sound — they're often fetched separately).
      const STREAM_LABELS = { video: "video", audio: "sound", "video+audio": "video" };
      let parts = "";
      if (job.items > 1) parts = ` · video ${job.item} of ${job.items}`;
      else if (job.stages > 1) parts = ` · ${job.stage}/${job.stages} ${STREAM_LABELS[job.stream] || ""}`.trimEnd();
      const bits = [
        job.percent != null ? `${Math.floor(job.percent)}%` : "Downloading",
        job.speed ? `${formatBytes(job.speed)}/s` : null,
        job.eta ? `${formatDuration(job.eta)} left` : null,
      ];
      return bits.filter(Boolean).join(" · ") + parts;
    }
    case JOB_STATUS.PROCESSING:
      return STEP_LABELS[job.step] || "Processing…";
    case JOB_STATUS.DONE:
      return `Saved · ${fileName(job.files?.[0])}`;
    case JOB_STATUS.CANCELLED:
      return "Cancelled";
    case JOB_STATUS.ERROR:
      return job.error || "Failed";
    default:
      return "";
  }
}

function renderJob(job) {
  const active = ACTIVE_STATUSES.has(job.status);
  const actions = el("div", { className: "job-actions" });
  if (active) {
    actions.append(el("button", {
      className: "link-btn", type: "button", textContent: "Cancel",
      onclick: () => callBackground(MSG.CANCEL_DOWNLOAD, { jobId: job.id }).catch(() => {}),
    }));
  } else if (job.status === JOB_STATUS.DONE && job.files?.length) {
    actions.append(el("button", {
      className: "link-btn", type: "button", textContent: "Show",
      title: "Show in folder",
      onclick: () => callBackground(MSG.REVEAL_FILE, { path: job.files[0] })
        .catch((error) => alert(error.message)),
    }));
  }

  const statusClass = job.status === JOB_STATUS.ERROR ? "error" : job.status === JOB_STATUS.DONE ? "done" : "";
  const item = el("li", { className: "job" },
    el("div", { className: "job-title", textContent: `${job.label} · ${job.title}`, title: job.title }),
    el("div", { className: `job-status ${statusClass}`, textContent: jobStatusText(job) }),
    actions,
  );

  if (active) {
    const indeterminate = job.percent == null;
    const bar = el("div", { className: `progress${indeterminate ? " indeterminate" : ""}` },
      el("div", { style: `width:${indeterminate ? 0 : job.percent}%` }));
    item.append(bar);
  }
  return item;
}

function renderJobs(jobs = []) {
  $("downloads").hidden = jobs.length === 0;
  $("clear-btn").hidden = !jobs.some((j) => !ACTIVE_STATUSES.has(j.status));
  $("job-list").replaceChildren(...jobs.map(renderJob));
}

async function watchJobs() {
  const stored = await chrome.storage.session.get(JOBS_STORAGE_KEY);
  renderJobs(stored[JOBS_STORAGE_KEY]);
  chrome.storage.session.onChanged.addListener((changes) => {
    if (JOBS_STORAGE_KEY in changes) renderJobs(changes[JOBS_STORAGE_KEY].newValue);
  });
}

// ---------------------------------------------------------------------------
// Footer: helper status + yt-dlp update
// ---------------------------------------------------------------------------

async function loadHelperStatus() {
  const status = $("helper-status");
  try {
    const info = await callBackground(MSG.HELPER_STATUS);
    const warnings = [!info.ffmpeg && "ffmpeg missing", !info.deno && "deno missing"].filter(Boolean);
    status.textContent = `yt-dlp ${info.ytdlp_version}${warnings.length ? ` · ⚠ ${warnings.join(", ")}` : ""}`;
    $("update-btn").hidden = false;
  } catch {
    status.textContent = "Helper not connected";
  }
}

async function updateYtDlp() {
  const button = $("update-btn");
  button.disabled = true;
  button.textContent = "Updating…";
  try {
    const result = await callBackground(MSG.UPDATE_YTDLP);
    $("helper-status").textContent = `yt-dlp ${result.ytdlp_version}`;
    button.textContent = result.restart_required ? "Updated ✓" : "Up to date ✓";
  } catch (error) {
    button.textContent = "Update failed";
    button.title = error.message;
  }
}

// ---------------------------------------------------------------------------
// Embedded-panel plumbing
// ---------------------------------------------------------------------------

function setupEmbedding() {
  if (params.get("tab") === "1") document.body.classList.add("tab");
  if (!embedded) return;
  document.body.classList.add("embedded");
  $("close-btn").hidden = false;
  $("close-btn").addEventListener("click", () => parent.postMessage({ type: "vidgrab:close-panel" }, "*"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") parent.postMessage({ type: "vidgrab:close-panel" }, "*");
  });
  // Let the host page size the iframe to our content.
  new ResizeObserver(() => {
    parent.postMessage({ type: "vidgrab:resize", height: document.querySelector(".app").offsetHeight }, "*");
  }).observe(document.querySelector(".app"));
}

// ---------------------------------------------------------------------------

async function init() {
  setupEmbedding();
  state.settings = await getSettings();

  for (const button of document.querySelectorAll(".segmented button")) {
    button.addEventListener("click", () => setKind(button.dataset.kind));
  }
  $("download-btn").addEventListener("click", () => startDownload());
  $("playlist-btn").addEventListener("click", () => startDownload({ playlist: true }));
  $("retry-btn").addEventListener("click", () => { loadInfo(); loadHelperStatus(); });
  $("clear-btn").addEventListener("click", () => callBackground(MSG.CLEAR_FINISHED));
  $("update-btn").addEventListener("click", updateYtDlp);
  $("settings-btn").addEventListener("click", () => chrome.runtime.openOptionsPage());

  watchJobs();
  loadHelperStatus();
  loadInfo();
}

init();
