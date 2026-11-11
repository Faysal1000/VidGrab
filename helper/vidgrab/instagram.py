"""Fallback for Instagram stories when yt-dlp's own story extractor fails.

yt-dlp reads stories from Instagram's ``feed/reels_media`` API. In late 2026
Instagram started answering that API with HTTP 500, and yt-dlp reports it as
"You need to log in" even with valid cookies (yt-dlp issues #17755, #17918).

The story page itself still embeds the same data as JSON
(``"xdt_api__v1__feed__reels_media": {"reels_media": [...]}``), so we fetch
the page with the user's cookies, pull the video URL out of it and hand
yt-dlp a ready-made info dict. Once yt-dlp is fixed, its extractor succeeds
first and this module is simply not used.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

from yt_dlp.networking import Request

log = logging.getLogger(__name__)

STORY_URL = re.compile(
    r"https?://(?:www\.)?instagram\.com/stories/(?P<user>[^/?#]+)(?:/(?P<id>\d+))?")
_REELS_MEDIA_KEY = '"xdt_api__v1__feed__reels_media"'


class StoryError(Exception):
    """The story page was readable but has nothing we can download."""


def is_story_url(url: str) -> bool:
    match = STORY_URL.match(url)
    return bool(match) and match["user"] != "highlights"


def story_info(ydl: Any, url: str) -> dict[str, Any] | None:
    """An info dict for the story at ``url`` (for ``ydl.process_ie_result``), or None."""
    match = STORY_URL.match(url)
    if not match:
        return None
    html = _fetch_page(ydl, url)
    items = [item for reel in _reels_media(html) for item in reel.get("items") or []]
    if not items:
        log.info("story fallback: no story data in page (logged out or story expired?)")
        return None
    item = _pick_item(items, match["id"])
    return _to_info(item, match["user"], url)


def parse_story_page(html: str, story_id: str | None, username: str, url: str) -> dict[str, Any] | None:
    """Pure parsing step, split out for tests."""
    items = [item for reel in _reels_media(html) for item in reel.get("items") or []]
    return _to_info(_pick_item(items, story_id), username, url) if items else None


# -- internals ----------------------------------------------------------------


def _fetch_page(ydl: Any, url: str) -> str:
    extensions = {}
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        if ydl._impersonate_target_available(ImpersonateTarget("chrome")):
            extensions["impersonate"] = ImpersonateTarget("chrome")
    except Exception:  # impersonation is optional
        pass
    request = Request(url, headers={"Accept": "text/html,application/xhtml+xml",
                                    "Sec-Fetch-Mode": "navigate"}, extensions=extensions)
    with ydl.urlopen(request) as response:
        return response.read().decode("utf-8", "replace")


def _reels_media(html: str) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    start = 0
    while (index := html.find(_REELS_MEDIA_KEY, start)) != -1:
        start = index + len(_REELS_MEDIA_KEY)
        colon = html.find(":", start)
        if colon == -1:
            break
        try:
            value, _ = decoder.raw_decode(html, colon + 1)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield from (reel for reel in value.get("reels_media") or [] if isinstance(reel, dict))


def _pick_item(items: list[dict[str, Any]], story_id: str | None) -> dict[str, Any]:
    if story_id:
        for item in items:
            if str(item.get("pk")) == story_id or str(item.get("id", "")).split("_")[0] == story_id:
                return item
    return items[0]


def _to_info(item: dict[str, Any], username: str, url: str) -> dict[str, Any]:
    videos = [v for v in item.get("video_versions") or [] if v.get("url")]
    if not videos:
        raise StoryError("This story is a photo, not a video.")
    formats = [{
        "format_id": f"story-{index}",
        "url": video["url"],
        "ext": "mp4",
        "width": video.get("width"),
        "height": video.get("height"),
        "vcodec": "h264",
        "acodec": "aac" if item.get("has_audio", True) else "none",
    } for index, video in enumerate(videos)]
    user = item.get("user") or {}
    candidates = (item.get("image_versions2") or {}).get("candidates") or []
    story_id = str(item.get("pk") or str(item.get("id", "story")).split("_")[0])
    return {
        "id": story_id,
        "title": f"Story by {username}",
        "uploader": user.get("full_name") or username,
        "uploader_id": username,
        "thumbnail": candidates[0].get("url") if candidates else None,
        "duration": item.get("video_duration"),
        "timestamp": item.get("taken_at"),
        "formats": formats,
        "webpage_url": url,
        "original_url": url,
        "webpage_url_basename": story_id,
        "webpage_url_domain": "instagram.com",
        "extractor": "instagram:story",
        "extractor_key": "InstagramStory",
    }
