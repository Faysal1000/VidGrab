"""Turn yt-dlp metadata into user-facing choices, and choices back into yt-dlp options.

The extension never sees raw yt-dlp format IDs. It gets a short summary
(available heights, containers, audio formats) and sends back a "choice":

    {"kind": "video", "quality": 1080 | None, "container": "mp4" | "webm" | "mkv"}
    {"kind": "audio", "format": "mp3" | "m4a" | "wav"}

Keeping this mapping in one place means site quirks are handled here rather
than in the UI.
"""

from __future__ import annotations

from typing import Any

VIDEO_CONTAINERS = ("mp4", "webm", "mkv")
AUDIO_FORMATS = ("mp3", "m4a", "wav")


class InvalidChoice(ValueError):
    pass


# ---------------------------------------------------------------------------
# Summaries (yt-dlp info dict -> what the popup shows)
# ---------------------------------------------------------------------------

def _first_entry(info: dict[str, Any]) -> dict[str, Any]:
    """Playlists (e.g. Instagram carousels) are summarised by their first video."""
    entries = [e for e in (info.get("entries") or []) if e]
    return entries[0] if entries else info


AUDIO_EXTENSIONS = {"m4a", "mp3", "aac", "opus", "ogg", "oga", "wav", "flac", "weba"}


# yt-dlp marks a missing stream with the string "none"; None means "unknown"
# (common for plain .mp4 files found by the generic extractor), which we treat
# as present.
def _has_video(fmt: dict[str, Any]) -> bool:
    vcodec = fmt.get("vcodec")
    if vcodec == "none":
        return False
    if vcodec is None:
        return bool(fmt.get("height")) or fmt.get("ext") not in AUDIO_EXTENSIONS
    return True


def _has_audio(fmt: dict[str, Any]) -> bool:
    return fmt.get("acodec") != "none"


def _size(fmt: dict[str, Any]) -> int | None:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    return int(size) if size else None


def _estimate_sizes(formats: list[dict[str, Any]], heights: list[int]) -> dict[int, int]:
    """Rough download size per quality: biggest video at that height + best audio."""
    audio_only = [f for f in formats if _has_audio(f) and not _has_video(f)]
    best_audio = max((_size(f) or 0 for f in audio_only), default=0)
    estimates: dict[int, int] = {}
    for height in heights:
        candidates = [f for f in formats if _has_video(f) and f.get("height") == height and _size(f)]
        if not candidates:
            continue
        best = max(candidates, key=lambda f: _size(f) or 0)
        extra = 0 if _has_audio(best) else best_audio
        estimates[height] = (_size(best) or 0) + extra
    return estimates


def summarize(info: dict[str, Any]) -> dict[str, Any]:
    entry = _first_entry(info)
    formats = entry.get("formats") or [entry]

    heights = sorted(
        {int(f["height"]) for f in formats if _has_video(f) and f.get("height")},
        reverse=True,
    )
    has_video = any(_has_video(f) for f in formats)
    has_audio = any(_has_audio(f) for f in formats)
    has_webm = any(f.get("ext") == "webm" and _has_video(f) for f in formats)

    containers = ["mp4", "mkv"] + (["webm"] if has_webm else [])
    sizes = _estimate_sizes(formats, heights)

    return {
        "title": entry.get("title") or info.get("title") or "video",
        "uploader": entry.get("uploader") or entry.get("channel") or info.get("uploader"),
        "thumbnail": entry.get("thumbnail") or info.get("thumbnail"),
        "duration": entry.get("duration"),
        "webpage_url": info.get("webpage_url") or entry.get("webpage_url"),
        "extractor": info.get("extractor_key") or entry.get("extractor_key"),
        "item_count": len([e for e in (info.get("entries") or []) if e]) or 1,
        "video": {
            "available": has_video,
            "qualities": [{"height": h, "size": sizes.get(h)} for h in heights],
            "containers": containers if has_video else [],
        },
        "audio": {
            "available": has_audio,
            "formats": list(AUDIO_FORMATS) if has_audio else [],
        },
    }


# ---------------------------------------------------------------------------
# Choices (what the user picked -> yt-dlp options)
# ---------------------------------------------------------------------------

def _video_options(choice: dict[str, Any]) -> dict[str, Any]:
    container = choice.get("container", "mp4")
    if container not in VIDEO_CONTAINERS:
        raise InvalidChoice(f"Unsupported container: {container}")

    quality = choice.get("quality")
    if quality is not None:
        try:
            quality = int(quality)
        except (TypeError, ValueError) as exc:
            raise InvalidChoice(f"Invalid quality: {quality!r}") from exc

    # format_sort picks the best stream at or below the requested height and,
    # for MP4, prefers H.264/AAC so the file plays everywhere (QuickTime, phones).
    # "proto:https" prefers direct downloads over HLS fragment streams, which
    # are much slower for the same quality.
    sort: list[str] = [f"res:{quality}"] if quality else ["res"]
    if container == "mp4":
        sort += ["vcodec:h264", "acodec:aac", "proto:https", "ext:mp4:m4a"]
        selector = "bv*+ba/b"
    elif container == "webm":
        sort += ["ext:webm:webm"]
        selector = "bv*[ext=webm]+ba[ext=webm]/b[ext=webm]/bv*+ba/b"
    else:  # mkv holds any codec, so just take the best streams
        selector = "bv*+ba/b"

    return {
        "format": selector,
        "format_sort": sort,
        "merge_output_format": container,
        "postprocessors": [
            # Single-file downloads (no merge) still end up in the chosen container.
            {"key": "FFmpegVideoRemuxer", "preferedformat": container},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ],
    }


def _audio_options(choice: dict[str, Any]) -> dict[str, Any]:
    audio_format = choice.get("format", "mp3")
    if audio_format not in AUDIO_FORMATS:
        raise InvalidChoice(f"Unsupported audio format: {audio_format}")
    return {
        "format": "ba/b",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                # "0" = best VBR quality for mp3; ignored by lossless/copy codecs.
                "preferredquality": "0",
            },
            {"key": "FFmpegMetadata", "add_metadata": True},
        ],
    }


def build_download_options(choice: dict[str, Any]) -> dict[str, Any]:
    kind = choice.get("kind")
    if kind == "video":
        return _video_options(choice)
    if kind == "audio":
        return _audio_options(choice)
    raise InvalidChoice(f"Unknown download kind: {kind!r}")


def describe_choice(choice: dict[str, Any]) -> str:
    """Short human label, e.g. '1080p MP4', 'MP3 audio' or 'Playlist · 720p MP4'."""
    if choice.get("kind") == "audio":
        label = f"{str(choice.get('format', 'mp3')).upper()} audio"
    else:
        quality = choice.get("quality")
        label = f"{quality}p" if quality else "Best"
        label = f"{label} {str(choice.get('container', 'mp4')).upper()}"
    return f"Playlist · {label}" if choice.get("playlist") else label
