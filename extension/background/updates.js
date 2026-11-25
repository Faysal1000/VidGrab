// One-click VidGrab updates.
//
// The helper checks the project's GitHub Releases as often as the user chose
// in Settings (every 1/7/15/30 days, or never = only when they click "Check
// for updates"); the result is cached here. When the user clicks "Update",
// the helper downloads and installs that release over the current files, and
// the extension then reloads itself — an unpacked extension re-reads its folder on reload.

import { getSettings } from "../shared/settings.js";

const CACHE_KEY = "vidgrab.updateCheck";
const DAY_MS = 24 * 60 * 60 * 1000;

export function compareVersions(a, b) {
  const pa = String(a).replace(/^v/i, "").split(".").map(Number);
  const pb = String(b).replace(/^v/i, "").split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff) return Math.sign(diff);
  }
  return 0;
}

export class Updater {
  #helper;
  #canUpdate;
  #onBusy;
  #updating = false;

  /**
   * @param helper     NativeHost
   * @param canUpdate  () => string|null — reason updating isn't allowed right now
   * @param onBusy     (busy: boolean) => void — keep the worker alive meanwhile
   */
  constructor(helper, { canUpdate, onBusy }) {
    this.#helper = helper;
    this.#canUpdate = canUpdate;
    this.#onBusy = onBusy;
  }

  get currentVersion() {
    return chrome.runtime.getManifest().version;
  }

  /**
   * @param force  check GitHub now ("Check for updates" button); otherwise only
   *               when the automatic interval has passed, or never if it's off.
   */
  async status({ force = false } = {}) {
    let record = (await chrome.storage.local.get(CACHE_KEY))[CACHE_KEY];
    const { updateCheckDays } = await getSettings();
    const due = updateCheckDays > 0 && (!record || Date.now() - record.checkedAt > updateCheckDays * DAY_MS);
    if (force || due) {
      const info = await this.#helper.request("check_update");
      record = { checkedAt: Date.now(), latest: info.latest, tag: info.tag, notes: info.notes, url: info.url };
      await chrome.storage.local.set({ [CACHE_KEY]: record });
    }
    return {
      ...(record || {}),
      checked: Boolean(record),
      current: this.currentVersion,
      available: Boolean(record?.latest) && compareVersions(record.latest, this.currentVersion) > 0,
      updating: this.#updating,
    };
  }

  async apply() {
    if (this.#updating) throw new Error("An update is already being installed.");
    const blocked = this.#canUpdate();
    if (blocked) throw new Error(blocked);
    const status = await this.status({ force: true });
    if (!status.available) throw new Error(`VidGrab ${status.current} is already up to date.`);

    this.#updating = true;
    this.#onBusy(true);
    try {
      await this.#helper.request("self_update", { tag: status.tag });
    } finally {
      this.#updating = false;
      this.#onBusy(false);
    }
    await chrome.storage.local.remove(CACHE_KEY);
    // Give the UI a moment to show "Updated", then load the new files.
    setTimeout(() => chrome.runtime.reload(), 800);
    return { version: status.latest };
  }
}
