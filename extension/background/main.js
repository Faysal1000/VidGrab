// Background service worker: routes UI requests to the native helper and
// tracks download jobs.

import { MSG, JOB_STATUS } from "../shared/messages.js";
import { getSettings } from "../shared/settings.js";
import { describeChoice, fileName } from "../shared/format.js";
import { NativeHost } from "./native-host.js";
import { JobStore } from "./job-store.js";
import { cookiesFor } from "./cookies.js";

const HOST_NAME = "com.vidgrab.helper"; // must match installer/install.py
const CONTEXT_MENU_ID = "vidgrab-download";
const EXTENSION_ORIGIN = new URL(chrome.runtime.getURL("/")).origin;

const helper = new NativeHost(HOST_NAME);
const jobs = new JobStore();

// ---------------------------------------------------------------------------
// Request handlers (popup / options page -> background)
// ---------------------------------------------------------------------------

async function getInfo({ urls }) {
  const candidates = [...new Set((urls || []).filter(Boolean))];
  if (!candidates.length) throw new Error("No video found on this page.");
  const settings = await getSettings();
  return helper.request("info", {
    urls: candidates,
    cookies: await cookiesFor(candidates[0], settings),
    user_agent: navigator.userAgent,
  });
}

async function startDownload({ url, choice, meta = {} }) {
  await jobs.ready();
  const settings = await getSettings();
  const job = jobs.create({
    url,
    choice,
    label: describeChoice(choice),
    title: meta.title || url,
    thumbnail: meta.thumbnail || null,
  });

  // Runs in the background; the popup follows progress via storage.
  runDownload(job.id, {
    url,
    choice,
    output_dir: settings.downloadDir,
    cookies: await cookiesFor(url, settings),
    user_agent: navigator.userAgent,
  });
  return { jobId: job.id };
}

async function runDownload(jobId, params) {
  const onProgress = (data) => {
    if (data.phase === "downloading") {
      jobs.update(jobId, {
        status: JOB_STATUS.DOWNLOADING,
        percent: data.percent,
        speed: data.speed,
        eta: data.eta,
        stream: data.stream,
        stage: data.stage,
        stages: data.stages,
        item: data.item,
        items: data.items,
      });
    } else if (data.phase === "processing") {
      jobs.update(jobId, { status: JOB_STATUS.PROCESSING, step: data.step, percent: null });
    }
  };

  try {
    const result = await helper.request("download", params, { id: jobId, onProgress });
    if (result.cancelled) {
      jobs.update(jobId, { status: JOB_STATUS.CANCELLED }, { immediate: true });
      return;
    }
    jobs.update(jobId, {
      status: JOB_STATUS.DONE,
      percent: 100,
      files: result.files,
      title: result.title || jobs.get(jobId)?.title,
    }, { immediate: true });
    const saved = result.files.length > 1 ? `${result.files.length} videos saved` : fileName(result.files[0]);
    notify(jobId, "Download complete", saved);
  } catch (error) {
    jobs.update(jobId, { status: JOB_STATUS.ERROR, error: error.message }, { immediate: true });
    notify(jobId, "Download failed", error.message);
  }
}

async function cancelDownload({ jobId }) {
  const job = jobs.get(jobId);
  if (!job) return { cancelled: false };
  return helper.request("cancel", { job_id: jobId });
}

function revealFile({ path }) {
  return helper.request("reveal", { path });
}

async function clearFinished() {
  await jobs.ready();
  jobs.clearFinished();
  return {};
}

function helperStatus() {
  return helper.request("ping");
}

async function updateYtDlp() {
  const result = await helper.request("update");
  // The running helper still has the old yt-dlp loaded; restart it when free.
  if (result.restart_required) helper.restartIfIdle();
  return result;
}

const HANDLERS = {
  [MSG.GET_INFO]: getInfo,
  [MSG.START_DOWNLOAD]: startDownload,
  [MSG.CANCEL_DOWNLOAD]: cancelDownload,
  [MSG.REVEAL_FILE]: revealFile,
  [MSG.CLEAR_FINISHED]: clearFinished,
  [MSG.HELPER_STATUS]: helperStatus,
  [MSG.UPDATE_YTDLP]: updateYtDlp,
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handler = HANDLERS[message?.type];
  if (!handler) return false;

  // Only our own extension pages (popup, embedded panel, options) may drive
  // the helper — never a content script running inside a web page.
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(EXTENSION_ORIGIN)) {
    sendResponse({ ok: false, error: "Not allowed" });
    return false;
  }

  Promise.resolve()
    .then(() => handler(message))
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: error.message, code: error.code }));
  return true; // keep the channel open for the async response
});

// ---------------------------------------------------------------------------
// Badge + notifications
// ---------------------------------------------------------------------------

// While downloads run, call a trivial extension API every 20s. Each call
// resets the browser's 30s idle timer, so the service worker (which owns the
// connection to the helper) isn't put to sleep mid-download.
const KEEPALIVE_INTERVAL_MS = 20_000;
let keepAliveTimer = null;

function updateKeepAlive(activeCount) {
  if (activeCount && !keepAliveTimer) {
    keepAliveTimer = setInterval(() => chrome.runtime.getPlatformInfo(), KEEPALIVE_INTERVAL_MS);
  } else if (!activeCount && keepAliveTimer) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }
}

jobs.onChange(() => {
  const count = jobs.activeCount();
  updateKeepAlive(count);
  chrome.action.setBadgeText({ text: count ? String(count) : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#e98aa6" });
});

function notify(jobId, title, message) {
  chrome.notifications.create(jobId, {
    type: "basic",
    iconUrl: chrome.runtime.getURL("icons/icon128.png"),
    title,
    message: message || "",
  });
}

chrome.notifications.onClicked.addListener((jobId) => {
  const file = jobs.get(jobId)?.files?.[0];
  if (file) revealFile({ path: file }).catch(() => {});
  chrome.notifications.clear(jobId);
});

// ---------------------------------------------------------------------------
// Right-click menu: "Download video with VidGrab"
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(() => {
  // Installed, updated or reloaded: start with a clean downloads list and helper log.
  jobs.clearAll();
  helper.request("clear_log").catch(() => {}); // helper may not be installed yet

  chrome.contextMenus.create({
    id: CONTEXT_MENU_ID,
    title: "Download video with VidGrab",
    contexts: ["video", "link", "page"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== CONTEXT_MENU_ID || !tab?.id) return;
  chrome.tabs
    .sendMessage(tab.id, {
      type: MSG.OPEN_PANEL,
      source: "context-menu",
      linkUrl: info.linkUrl,
      srcUrl: info.srcUrl,
    }, { frameId: info.frameId ?? 0 })
    .catch(() => {
      // No content script (e.g. the tab was open before install): fall back to a new tab.
      const url = info.linkUrl || info.pageUrl;
      const panel = chrome.runtime.getURL(`popup/popup.html?url=${encodeURIComponent(url)}&tab=1`);
      chrome.tabs.create({ url: panel });
    });
});
