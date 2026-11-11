// Request/response client for the native helper (see helper/vidgrab/commands.py).
//
// One long-lived port is shared by all requests. An open native port also
// keeps the MV3 service worker alive, which is exactly what we want while
// downloads run; when nothing is pending we disconnect after a short idle
// period so the helper process exits.

const IDLE_DISCONNECT_MS = 30_000;

export class HelperError extends Error {
  constructor(message, code = "HELPER_ERROR") {
    super(message);
    this.code = code;
  }
}

function classifyDisconnect(message = "") {
  const text = message.toLowerCase();
  if (text.includes("not found") || text.includes("forbidden")) {
    return new HelperError(
      "The VidGrab helper isn't installed (or isn't allowed for this browser). Run the installer, then restart the browser.",
      "HELPER_MISSING",
    );
  }
  return new HelperError(message || "The VidGrab helper stopped unexpectedly.", "HELPER_CRASHED");
}

export class NativeHost {
  #name;
  #port = null;
  #pending = new Map(); // id -> { resolve, reject, onProgress }
  #idleTimer = null;
  #counter = 0;

  constructor(name) {
    this.#name = name;
  }

  /**
   * Send a command. Resolves with the helper's `data`, rejects with HelperError.
   * @param {string} cmd
   * @param {object} params
   * @param {{id?: string, onProgress?: (data: object) => void}} [options]
   */
  request(cmd, params = {}, { id, onProgress } = {}) {
    const requestId = id ?? `req-${Date.now()}-${++this.#counter}`;
    return new Promise((resolve, reject) => {
      let port;
      try {
        port = this.#ensurePort();
      } catch (error) {
        reject(classifyDisconnect(error.message));
        return;
      }
      this.#pending.set(requestId, { resolve, reject, onProgress });
      this.#clearIdleTimer();
      try {
        port.postMessage({ id: requestId, cmd, ...params });
      } catch (error) {
        this.#pending.delete(requestId);
        reject(classifyDisconnect(error.message));
      }
    });
  }

  get busy() {
    return this.#pending.size > 0;
  }

  /** Close the helper now (e.g. to load an updated yt-dlp) if nothing is running. */
  restartIfIdle() {
    if (!this.busy) this.#disconnect();
  }

  #ensurePort() {
    if (this.#port) return this.#port;
    const port = chrome.runtime.connectNative(this.#name);
    port.onMessage.addListener((message) => this.#onMessage(message));
    port.onDisconnect.addListener(() => {
      const error = classifyDisconnect(chrome.runtime.lastError?.message);
      if (this.#port === port) this.#port = null;
      this.#rejectAll(error);
    });
    this.#port = port;
    return port;
  }

  #onMessage(message) {
    const entry = this.#pending.get(message?.id);
    if (!entry) return;
    if (message.type === "progress") {
      entry.onProgress?.(message.data);
      return;
    }
    this.#pending.delete(message.id);
    if (message.type === "result") entry.resolve(message.data);
    else entry.reject(new HelperError(message.error || "Unknown helper error"));
    this.#scheduleIdleDisconnect();
  }

  #rejectAll(error) {
    const entries = [...this.#pending.values()];
    this.#pending.clear();
    this.#clearIdleTimer();
    entries.forEach((entry) => entry.reject(error));
  }

  #scheduleIdleDisconnect() {
    if (this.busy) return;
    this.#clearIdleTimer();
    this.#idleTimer = setTimeout(() => this.#disconnect(), IDLE_DISCONNECT_MS);
  }

  #clearIdleTimer() {
    if (this.#idleTimer) clearTimeout(this.#idleTimer);
    this.#idleTimer = null;
  }

  #disconnect() {
    this.#clearIdleTimer();
    const port = this.#port;
    this.#port = null;
    port?.disconnect();
  }
}
