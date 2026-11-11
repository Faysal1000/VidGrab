// Download jobs, mirrored into chrome.storage.session so the popup can render
// them (and keep showing them after it's closed and reopened).

import { ACTIVE_STATUSES, JOBS_STORAGE_KEY, JOB_STATUS } from "../shared/messages.js";

const MAX_JOBS_KEPT = 30;
const PERSIST_DELAY_MS = 200;

export class JobStore {
  #jobs = new Map();
  #persistTimer = null;
  #ready;
  #listeners = new Set();

  constructor() {
    this.#ready = this.#load();
  }

  ready() {
    return this.#ready;
  }

  /** Called with the job list whenever it changes (e.g. to update the badge). */
  onChange(listener) {
    this.#listeners.add(listener);
  }

  create(fields) {
    const id = `job-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const job = {
      id,
      status: JOB_STATUS.QUEUED,
      percent: null,
      speed: null,
      eta: null,
      step: null,
      files: [],
      error: null,
      createdAt: Date.now(),
      ...fields,
    };
    this.#jobs.set(id, job);
    this.#trim();
    this.#changed({ immediate: true });
    return job;
  }

  get(id) {
    return this.#jobs.get(id);
  }

  update(id, patch, { immediate = false } = {}) {
    const job = this.#jobs.get(id);
    if (!job) return;
    Object.assign(job, patch);
    this.#changed({ immediate });
  }

  activeCount() {
    return [...this.#jobs.values()].filter((j) => ACTIVE_STATUSES.has(j.status)).length;
  }

  clearFinished() {
    for (const [id, job] of this.#jobs) {
      if (!ACTIVE_STATUSES.has(job.status)) this.#jobs.delete(id);
    }
    this.#changed({ immediate: true });
  }

  async #load() {
    const stored = await chrome.storage.session.get(JOBS_STORAGE_KEY);
    for (const job of stored[JOBS_STORAGE_KEY] ?? []) {
      // The worker (and with it the helper connection) restarted mid-download.
      if (ACTIVE_STATUSES.has(job.status)) {
        job.status = JOB_STATUS.ERROR;
        job.error = "Interrupted — the browser stopped the download. Please try again.";
      }
      this.#jobs.set(job.id, job);
    }
    this.#changed({ immediate: true });
  }

  #trim() {
    const finished = [...this.#jobs.values()]
      .filter((j) => !ACTIVE_STATUSES.has(j.status))
      .sort((a, b) => a.createdAt - b.createdAt);
    while (this.#jobs.size > MAX_JOBS_KEPT && finished.length) {
      this.#jobs.delete(finished.shift().id);
    }
  }

  #changed({ immediate }) {
    const jobs = [...this.#jobs.values()];
    this.#listeners.forEach((listener) => listener(jobs));
    if (this.#persistTimer) {
      if (!immediate) return; // a write is already scheduled
      clearTimeout(this.#persistTimer);
    }
    this.#persistTimer = setTimeout(() => this.#persist(), immediate ? 0 : PERSIST_DELAY_MS);
  }

  async #persist() {
    this.#persistTimer = null;
    const jobs = [...this.#jobs.values()].sort((a, b) => b.createdAt - a.createdAt);
    await chrome.storage.session.set({ [JOBS_STORAGE_KEY]: jobs });
  }
}
