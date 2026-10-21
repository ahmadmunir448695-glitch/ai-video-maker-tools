/** Small formatting helpers shared across views. */

export function formatBytes(bytes) {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

/** Seconds as m:ss (or h:mm:ss past an hour), for durations and timecodes. */
export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

/** Seconds as m:ss.t — the extra tenth matters when setting a trim point. */
export function formatTimecode(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function formatRelativeTime(value) {
  if (!value) return "";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);

  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(value).toLocaleDateString();
}

export function formatPercent(value) {
  return `${Math.max(0, Math.min(100, Math.round(value || 0)))}%`;
}

/** Human label for an aspect ratio key, including where it is normally used. */
export function aspectLabel(aspect) {
  return (
    {
      original: "Original",
      "9:16": "Vertical 9:16",
      "1:1": "Square 1:1",
      "16:9": "Landscape 16:9",
      "4:5": "Portrait 4:5",
    }[aspect] || aspect
  );
}

export function aspectHint(aspect) {
  return (
    {
      original: "Keeps the shape of the video you uploaded.",
      "9:16": "Full screen for TikTok, Reels and Shorts.",
      "1:1": "Square, for an Instagram feed post.",
      "16:9": "Widescreen, for YouTube.",
      "4:5": "Taller feed post, for Instagram.",
    }[aspect] || ""
  );
}

export function speedLabel(speed) {
  if (speed === 1) return "Normal";
  return `${speed}x`;
}

export function qualityLabel(quality) {
  return { low: "Small file (480p)", medium: "Balanced (720p)", high: "Best (1080p)" }[quality] || quality;
}

export function statusLabel(status) {
  return (
    {
      pending: "Waiting to start",
      queued: "In the queue",
      processing: "Working on it",
      succeeded: "Ready",
      failed: "Failed",
      cancelled: "Cancelled",
    }[status] || status
  );
}
