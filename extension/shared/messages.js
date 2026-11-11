// Message types exchanged between extension pages and the background worker.
// Content scripts can't import modules, so content/main.js repeats the few
// it uses — keep them in sync.

export const MSG = Object.freeze({
  // popup/options -> background
  GET_INFO: "vidgrab:get-info",
  START_DOWNLOAD: "vidgrab:start-download",
  CANCEL_DOWNLOAD: "vidgrab:cancel-download",
  REVEAL_FILE: "vidgrab:reveal-file",
  CLEAR_FINISHED: "vidgrab:clear-finished",
  HELPER_STATUS: "vidgrab:helper-status",
  UPDATE_YTDLP: "vidgrab:update-ytdlp",

  // background/popup -> content script
  RESOLVE_ACTIVE_VIDEO: "vidgrab:resolve-active-video",
  OPEN_PANEL: "vidgrab:open-panel",

  // embedded popup iframe -> content script (window.postMessage)
  CLOSE_PANEL: "vidgrab:close-panel",
});

export const JOBS_STORAGE_KEY = "vidgrab.jobs";

export const JOB_STATUS = Object.freeze({
  QUEUED: "queued",
  DOWNLOADING: "downloading",
  PROCESSING: "processing",
  DONE: "done",
  ERROR: "error",
  CANCELLED: "cancelled",
});

export const ACTIVE_STATUSES = new Set([
  JOB_STATUS.QUEUED,
  JOB_STATUS.DOWNLOADING,
  JOB_STATUS.PROCESSING,
]);

/** Send a message to the background worker and unwrap {ok, data, error}. */
export async function callBackground(type, payload = {}) {
  const response = await chrome.runtime.sendMessage({ type, ...payload });
  if (!response) throw new Error("No response from the extension background.");
  if (!response.ok) {
    const error = new Error(response.error || "Unknown error");
    error.code = response.code;
    throw error;
  }
  return response.data;
}
