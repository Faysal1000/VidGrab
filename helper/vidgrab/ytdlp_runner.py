"""Thin wrapper around the yt-dlp Python API: fetch info and run downloads."""

from __future__ import annotations

import glob
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import DownloadCancelled, DownloadError

from . import formats
from . import instagram
from .cookies import cookie_file, describe_cookies
from .environment import Tools

log = logging.getLogger("vidgrab.ytdlp")

ProgressCallback = Callable[[dict[str, Any]], None]

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"
# Playlists get their own folder, with files numbered in playlist order.
PLAYLIST_OUTPUT_TEMPLATE = "%(playlist_title,playlist_id).80B/%(playlist_index)03d - %(title).120B [%(id)s].%(ext)s"
PROGRESS_INTERVAL_SECONDS = 0.25
# Our own bookkeeping postprocessors; not shown to the user as a "processing" step.
INTERNAL_STEPS = {"PlanRecorder"}


class JobCancelled(DownloadCancelled):
    """Raised from our hooks to stop a job.

    Subclassing yt-dlp's DownloadCancelled matters: yt-dlp always re-raises it,
    even with "ignoreerrors" (used for playlists), so a cancel stops the whole
    queue instead of just skipping to the next video.
    """


class FetchError(Exception):
    """A user-presentable failure (message is already cleaned up)."""


class _YtDlpLogger:
    """Route yt-dlp output to our log file; stdout belongs to the protocol."""

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            log.debug(msg)

    def info(self, msg: str) -> None:
        log.info(msg)

    def warning(self, msg: str) -> None:
        log.warning(msg)

    def error(self, msg: str) -> None:
        log.error(msg)


def clean_error(error: BaseException) -> str:
    message = _ANSI.sub("", str(error)).strip()
    message = re.sub(r"^ERROR:\s*", "", message)
    lowered = message.lower()
    if "sign in to confirm" in lowered and "bot" in lowered:
        message += (" — YouTube wants a login. Turn on 'Use my login for YouTube' in the"
                    " extension settings and make sure you're signed in to YouTube.")
    elif "login" in lowered or "log in" in lowered or "cookies" in lowered:
        message += " — Make sure you're logged in to this site in your browser, then try again."
    elif "unsupported url" in lowered:
        message = "This page isn't supported, or no downloadable video was found on it."
    return message


def _base_options(tools: Tools, cookiefile: str | None,
                  user_agent: str | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "logger": _YtDlpLogger(),
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "color": {"stdout": "no_color", "stderr": "no_color"},
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
    }
    if tools.ffmpeg:
        options["ffmpeg_location"] = tools.ffmpeg
    if tools.deno:
        # YouTube requires a JS runtime to unlock most formats.
        options["js_runtimes"] = {"deno": {"path": tools.deno}}
    if cookiefile:
        options["cookiefile"] = cookiefile
    if user_agent:
        # Same user-agent as the browser the cookies came from, so sites don't
        # treat the session as hijacked.
        options["http_headers"] = {"User-Agent": user_agent}
    return options


def _extract(ydl: yt_dlp.YoutubeDL, url: str, download: bool) -> dict[str, Any] | None:
    """ydl.extract_info with site-specific fallbacks for known yt-dlp breakages."""
    try:
        return ydl.extract_info(url, download=download)
    except DownloadError as exc:
        if not instagram.is_story_url(url):
            raise
        log.info("yt-dlp story extractor failed (%s); trying the story page instead", exc)
        try:
            story = instagram.story_info(ydl, url)
        except instagram.StoryError as story_exc:
            raise FetchError(str(story_exc)) from exc
        except Exception as fallback_exc:
            log.warning("story page fallback failed: %s", fallback_exc)
            raise exc from None
        if not story:
            raise FetchError("Instagram didn't return this story. It may have expired, or this "
                             "account's stories aren't visible to you.") from exc
        return ydl.process_ie_result(story, download=download)


def _has_playlist_param(url: str) -> bool:
    """e.g. youtube.com/watch?v=X&list=PL… (a video opened from a playlist or Mix)."""
    return "list" in parse_qs(urlparse(url).query)


def _probe_playlist(url: str, options: dict[str, Any]) -> dict[str, Any] | None:
    """Title and size of the playlist a video URL belongs to, without listing it all."""
    probe_options = {**options, "noplaylist": False, "extract_flat": "in_playlist",
                     "playlist_items": "1", "lazy_playlist": True}
    try:
        with yt_dlp.YoutubeDL(probe_options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        log.info("playlist probe failed for %s: %s", url, exc)
        return None
    if not info or info.get("_type") != "playlist":
        return None
    return {
        "title": info.get("title") or "Playlist",
        "count": info.get("playlist_count"),
        "url": info.get("webpage_url") or url,
    }


def _playlist_from_info(info: dict[str, Any], url: str) -> dict[str, Any] | None:
    """The URL itself was a playlist page (or a multi-video post)."""
    entries = [e for e in info.get("entries") or [] if e]
    if len(entries) < 2 and (info.get("playlist_count") or 0) < 2:
        return None
    return {
        "title": info.get("title") or "Playlist",
        "count": info.get("playlist_count") or len(entries),
        "url": info.get("webpage_url") or url,
    }


def fetch_info(urls: list[str], tools: Tools, cookies: list[dict] | None,
               user_agent: str | None = None) -> dict[str, Any]:
    """Try each candidate URL in order and summarise the first that works.

    The summary describes the single video. If it belongs to a playlist, that
    is reported separately under "playlist" so the UI can offer it as an
    explicit extra option.
    """
    errors: list[str] = []
    log.info("info: %s", describe_cookies(cookies))
    with cookie_file(cookies) as cookiefile, ThreadPoolExecutor(max_workers=1) as pool:
        options = _base_options(tools, cookiefile, user_agent)
        for url in urls:
            # Look up the playlist in parallel so it doesn't slow the panel down.
            probe = pool.submit(_probe_playlist, url, options) if _has_playlist_param(url) else None
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = _extract(ydl, url, download=False)
                if not info:
                    raise FetchError("No video information returned")
                info = ydl.sanitize_info(info)
            except Exception as exc:  # yt-dlp raises many types; report them all
                log.warning("info failed for %s: %s", url, exc)
                errors.append(clean_error(exc))
                continue

            summary = formats.summarize(info)
            summary["source_url"] = url
            summary["playlist"] = _playlist_from_info(info, url)
            if summary["playlist"]:
                # Single-video downloads should target the first video itself.
                first = next((e for e in info.get("entries") or [] if e), {})
                summary["source_url"] = first.get("webpage_url") or first.get("original_url") or url
            elif probe:
                summary["playlist"] = probe.result()
            return summary
    raise FetchError(errors[0] if errors else "No URL to inspect")


class OverallProgress:
    """Combine per-stream progress into one 0-100% figure.

    YouTube & co. serve video and audio as separate streams that yt-dlp
    downloads one after another and then merges. Reporting each stream's own
    percentage makes the bar jump back to 0% halfway, which looks like the
    download restarted — so we weight each stream by its size instead.
    """

    def __init__(self) -> None:
        self._order: list[str] = []
        self._sizes: dict[str, int | None] = {}
        self._kinds: dict[str, str] = {}

    def set_plan(self, info: dict[str, Any]) -> None:
        streams = info.get("requested_formats") or [info]
        self._order = [str(f.get("format_id")) for f in streams]
        self._sizes = {str(f.get("format_id")): f.get("filesize") or f.get("filesize_approx")
                       for f in streams}
        self._kinds = {str(f.get("format_id")): _stream_kind(f) for f in streams}

    def update(self, format_id: str, downloaded: int, total: int | None,
               fraction: float | None) -> dict[str, Any]:
        """Returns percent (overall), stage index/count and the stream kind."""
        if format_id not in self._order:  # plan unknown (e.g. generic extractor)
            self._order.append(format_id)
            self._kinds.setdefault(format_id, "video")
        if total:
            self._sizes[format_id] = total
        index = self._order.index(format_id)
        count = len(self._order)

        sizes = [self._sizes.get(fid) for fid in self._order]
        if fraction is None:
            percent = None
        elif all(sizes):
            done = sum(sizes[:index]) + fraction * sizes[index]
            percent = done / sum(sizes) * 100
        else:  # sizes unknown: give each stream an equal share
            percent = (index + fraction) / count * 100

        remaining = None
        if all(sizes):
            remaining = sum(sizes[index:]) - downloaded
        return {
            "percent": None if percent is None else round(min(percent, 100.0), 1),
            "stage": index + 1,
            "stages": count,
            "stream": self._kinds.get(format_id, "video"),
            "remaining_bytes": remaining,
        }


def _stream_kind(fmt: dict[str, Any]) -> str:
    if fmt.get("vcodec") == "none":
        return "audio"
    if fmt.get("acodec") == "none":
        return "video"
    return "video+audio"


class PlanRecorderPP(PostProcessor):
    """Runs just before each download, when the chosen streams are known."""

    def __init__(self, progress: OverallProgress, cancel_event: threading.Event) -> None:
        super().__init__()
        self._progress = progress
        self._cancel_event = cancel_event

    def run(self, info: dict[str, Any]):
        if self._cancel_event.is_set():  # don't start the next playlist video
            raise JobCancelled()
        self._progress.set_plan(info)
        log.info("Downloading %s: formats %s", info.get("id"),
                 info.get("format_id"))
        return [], info


@dataclass
class DownloadJob:
    job_id: str
    url: str
    choice: dict[str, Any]
    output_dir: Path
    cookies: list[dict] | None = None
    user_agent: str | None = None
    playlist: bool = False  # download the whole playlist instead of one video
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _temp_files: set[str] = field(default_factory=set)
    _final_paths: list[str] = field(default_factory=list)
    _last_emit: float = 0.0
    _last_step: str | None = None
    _progress: OverallProgress = field(default_factory=OverallProgress)

    def cancel(self) -> None:
        self.cancel_event.set()

    # -- hooks --------------------------------------------------------------

    def _progress_hook(self, emit: ProgressCallback) -> Callable[[dict[str, Any]], None]:
        def hook(d: dict[str, Any]) -> None:
            if self.cancel_event.is_set():
                raise JobCancelled()
            if d.get("tmpfilename"):
                self._temp_files.add(d["tmpfilename"])
            if d.get("status") != "downloading":
                return

            now = time.monotonic()
            if now - self._last_emit < PROGRESS_INTERVAL_SECONDS:
                return
            self._last_emit = now

            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            if total:
                fraction = min(downloaded / total, 1.0)
            elif d.get("fragment_count"):
                fraction = (d.get("fragment_index") or 0) / d["fragment_count"]
            else:
                fraction = None

            info = d.get("info_dict") or {}
            overall = self._progress.update(str(info.get("format_id", "")), downloaded, total, fraction)
            speed = d.get("speed")
            remaining = overall.pop("remaining_bytes")
            # ETA for the whole video (all streams), not just the current one.
            eta = remaining / speed if remaining and speed else d.get("eta")

            item, items = info.get("playlist_index"), info.get("n_entries") or info.get("playlist_count")
            if self.playlist and item and items:
                # Playlist: the bar covers the whole list; ETA would only be for this video.
                if overall["percent"] is not None:
                    overall["percent"] = round(((item - 1) + overall["percent"] / 100) / items * 100, 1)
                overall.update(item=item, items=items)
                eta = None
            emit({
                "phase": "downloading",
                "speed": speed,
                "eta": round(eta) if eta else None,
                **overall,
            })
        return hook

    def _postprocessor_hook(self, emit: ProgressCallback) -> Callable[[dict[str, Any]], None]:
        def hook(d: dict[str, Any]) -> None:
            if d.get("status") == "started":
                step = d.get("postprocessor")
                if step in INTERNAL_STEPS:
                    return
                if step != self._last_step:  # yt-dlp may report the same step twice
                    self._last_step = step
                    emit({"phase": "processing", "step": step})
            elif d.get("status") == "finished":
                path = (d.get("info_dict") or {}).get("filepath")
                if path:
                    self._record_final(path)
        return hook

    def _record_final(self, path: str) -> None:
        # Postprocessors can rename the file; keep only the latest name per download.
        stem = os.path.splitext(path)[0]
        self._final_paths = [p for p in self._final_paths if os.path.splitext(p)[0] != stem]
        self._final_paths.append(path)

    # -- run ----------------------------------------------------------------

    def run(self, tools: Tools, emit: ProgressCallback) -> dict[str, Any]:
        if not tools.ffmpeg:
            raise FetchError("ffmpeg is not installed. Run the installer again to set it up.")
        emit({"phase": "starting"})
        with cookie_file(self.cookies) as cookiefile:
            options = _base_options(tools, cookiefile, self.user_agent)
            options.update(formats.build_download_options(self.choice))
            options.update({
                "paths": {"home": str(self.output_dir)},
                "progress_hooks": [self._progress_hook(emit)],
                "postprocessor_hooks": [self._postprocessor_hook(emit)],
                "windowsfilenames": True,
            })
            if self.playlist:
                options.update({
                    "noplaylist": False,
                    "outtmpl": {"default": PLAYLIST_OUTPUT_TEMPLATE},
                    # Skip private/removed videos instead of failing the whole list.
                    "ignoreerrors": "only_download",
                })
            else:
                options.update({
                    "noplaylist": True,
                    # If the URL is itself a playlist page, still take just one video.
                    "playlist_items": "1",
                    "outtmpl": {"default": OUTPUT_TEMPLATE},
                })
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.add_post_processor(PlanRecorderPP(self._progress, self.cancel_event), when="before_dl")
                    info = _extract(ydl, self.url, download=True)
            except (JobCancelled, DownloadError) as exc:
                if self.cancel_event.is_set() or isinstance(exc, JobCancelled):
                    self._remove_temp_files()
                    raise JobCancelled() from exc
                raise FetchError(clean_error(exc)) from exc

        files = [p for p in self._final_paths if os.path.exists(p)]
        if not files and info:
            for entry in [info, *(info.get("entries") or [])]:
                for download in (entry or {}).get("requested_downloads") or []:
                    if download.get("filepath") and os.path.exists(download["filepath"]):
                        files.append(download["filepath"])
        if not files:
            raise FetchError("Download finished but the output file could not be found.")
        return {"files": files, "title": (info or {}).get("title")}

    def _remove_temp_files(self) -> None:
        """Delete partial downloads, including HLS/DASH fragment files."""
        for path in self._temp_files:
            base = path[:-len(".part")] if path.endswith(".part") else path
            candidates = {path, base, base + ".part", base + ".ytdl",
                          *glob.glob(glob.escape(base) + ".part-Frag*"),
                          *glob.glob(glob.escape(path) + "-Frag*")}
            for candidate in candidates:
                if os.path.isfile(candidate):
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass
