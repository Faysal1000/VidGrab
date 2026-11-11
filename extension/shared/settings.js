// User settings, persisted in chrome.storage.sync.

export const DEFAULT_SETTINGS = Object.freeze({
  /** Absolute folder path; empty = the system Downloads folder. */
  downloadDir: "",
  /** Send this browser's login cookies so private/logged-in videos work. */
  useCookies: true,
  /**
   * YouTube is excluded from cookie sharing by default: yt-dlp can rotate
   * YouTube session cookies, which may sign you out in the browser. Only
   * needed for age-restricted videos or "confirm you're not a bot" errors.
   */
  useCookiesForYouTube: false,
  /** Show the floating download button on videos. */
  showOverlayButton: true,
  /** Remembered format choices. */
  lastKind: "video",
  lastContainer: "mp4",
  lastQuality: "1080",
  lastAudioFormat: "mp3",
});

export async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS, ...stored };
}

export async function saveSettings(partial) {
  await chrome.storage.sync.set(partial);
}
