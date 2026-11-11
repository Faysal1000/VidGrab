// Small display helpers shared by the popup and background.

export function formatBytes(bytes) {
  if (!bytes || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return "";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function describeChoice(choice) {
  const label = choice.kind === "audio"
    ? `${choice.format.toUpperCase()} audio`
    : `${choice.quality ? `${choice.quality}p` : "Best"} ${choice.container.toUpperCase()}`;
  return choice.playlist ? `Playlist · ${label}` : label;
}

export function fileName(path) {
  return String(path || "").split(/[\\/]/).pop();
}
