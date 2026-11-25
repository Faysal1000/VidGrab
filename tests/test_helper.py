"""Unit tests for the helper (no network). Run:

    helper/.venv/bin/python -m unittest discover tests
"""

from __future__ import annotations

import io
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))

from vidgrab import formats  # noqa: E402
from vidgrab.cookies import to_netscape  # noqa: E402
from vidgrab.protocol import MessageWriter, ProtocolError, read_message  # noqa: E402

try:  # needs yt-dlp (run with the helper venv's python)
    from vidgrab.ytdlp_runner import OverallProgress
except ImportError:
    OverallProgress = None


def frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return struct.pack("<I", len(body)) + body


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        out = io.BytesIO()
        MessageWriter(out).send({"id": "1", "type": "result", "data": {"ok": True}})
        out.seek(0)
        self.assertEqual(read_message(out), {"id": "1", "type": "result", "data": {"ok": True}})

    def test_eof_returns_none(self):
        self.assertIsNone(read_message(io.BytesIO(b"")))

    def test_truncated_body_raises(self):
        with self.assertRaises(ProtocolError):
            read_message(io.BytesIO(frame({"a": 1})[:-2]))

    def test_non_object_rejected(self):
        with self.assertRaises(ProtocolError):
            read_message(io.BytesIO(frame([1, 2])))


SAMPLE_INFO = {
    "title": "Clip",
    "uploader": "someone",
    "extractor_key": "Youtube",
    "webpage_url": "https://example.com/v",
    "formats": [
        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "ext": "m4a", "filesize": 1_000},
        {"format_id": "v1", "vcodec": "avc1", "acodec": "none", "height": 1080, "ext": "mp4", "filesize": 10_000},
        {"format_id": "v2", "vcodec": "vp9", "acodec": "none", "height": 720, "ext": "webm", "filesize": 5_000},
        {"format_id": "m", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "ext": "mp4", "filesize": 2_000},
    ],
}


class SummaryTests(unittest.TestCase):
    def test_qualities_sorted_with_sizes(self):
        summary = formats.summarize(SAMPLE_INFO)
        self.assertEqual([q["height"] for q in summary["video"]["qualities"]], [1080, 720, 360])
        sizes = {q["height"]: q["size"] for q in summary["video"]["qualities"]}
        self.assertEqual(sizes[1080], 11_000)  # video + best audio
        self.assertEqual(sizes[360], 2_000)    # already has audio

    def test_webm_offered_only_when_available(self):
        self.assertIn("webm", formats.summarize(SAMPLE_INFO)["video"]["containers"])
        no_webm = {**SAMPLE_INFO, "formats": SAMPLE_INFO["formats"][:2]}
        self.assertNotIn("webm", formats.summarize(no_webm)["video"]["containers"])

    def test_playlist_uses_first_entry(self):
        summary = formats.summarize({"title": "Album", "entries": [SAMPLE_INFO, SAMPLE_INFO]})
        self.assertEqual(summary["title"], "Clip")
        self.assertEqual(summary["item_count"], 2)

    def test_unknown_codecs_count_as_video_with_audio(self):
        # A bare <video src="clip.mp4"> found by yt-dlp's generic extractor.
        summary = formats.summarize({"title": "x", "formats": [{"format_id": "0", "ext": "mp4", "url": "u"}]})
        self.assertTrue(summary["video"]["available"])
        self.assertTrue(summary["audio"]["available"])
        self.assertEqual(summary["video"]["containers"], ["mp4", "mkv"])

    def test_audio_only_source(self):
        info = {"title": "Song", "formats": [SAMPLE_INFO["formats"][0]]}
        summary = formats.summarize(info)
        self.assertFalse(summary["video"]["available"])
        self.assertTrue(summary["audio"]["available"])


class ChoiceTests(unittest.TestCase):
    def test_mp4_prefers_h264_at_height(self):
        opts = formats.build_download_options({"kind": "video", "quality": 720, "container": "mp4"})
        self.assertEqual(opts["format_sort"][:2], ["res:720", "vcodec:h264"])
        self.assertEqual(opts["merge_output_format"], "mp4")

    def test_best_quality(self):
        opts = formats.build_download_options({"kind": "video", "quality": None, "container": "mkv"})
        self.assertEqual(opts["format_sort"], ["res"])

    def test_audio(self):
        opts = formats.build_download_options({"kind": "audio", "format": "mp3"})
        self.assertEqual(opts["postprocessors"][0]["preferredcodec"], "mp3")

    def test_invalid_choices(self):
        for bad in ({"kind": "video", "container": "avi"}, {"kind": "audio", "format": "flac"},
                    {"kind": "nope"}, {"kind": "video", "quality": "abc", "container": "mp4"}):
            with self.assertRaises(formats.InvalidChoice):
                formats.build_download_options(bad)

    def test_describe(self):
        self.assertEqual(formats.describe_choice({"kind": "video", "quality": 1080, "container": "mp4"}), "1080p MP4")
        self.assertEqual(formats.describe_choice({"kind": "audio", "format": "m4a"}), "M4A audio")


@unittest.skipIf(OverallProgress is None, "yt-dlp not installed in this interpreter")
class OverallProgressTests(unittest.TestCase):
    def make(self):
        progress = OverallProgress()
        progress.set_plan({"requested_formats": [
            {"format_id": "137", "vcodec": "avc1", "acodec": "none", "filesize": 900},
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "filesize": 100},
        ]})
        return progress

    def test_progress_never_jumps_back_between_streams(self):
        progress = self.make()
        end_of_video = progress.update("137", 900, 900, 1.0)
        start_of_audio = progress.update("140", 0, 100, 0.0)
        self.assertEqual(end_of_video["percent"], 90.0)
        self.assertEqual(start_of_audio["percent"], 90.0)
        self.assertEqual((start_of_audio["stage"], start_of_audio["stages"]), (2, 2))
        self.assertEqual(start_of_audio["stream"], "audio")
        self.assertEqual(progress.update("140", 50, 100, 0.5)["percent"], 95.0)

    def test_remaining_bytes_cover_all_streams(self):
        self.assertEqual(self.make().update("137", 400, 900, 400 / 900)["remaining_bytes"], 600)

    def test_unknown_sizes_split_equally(self):
        progress = OverallProgress()
        progress.set_plan({"requested_formats": [{"format_id": "v"}, {"format_id": "a"}]})
        self.assertEqual(progress.update("a", 0, None, 0.5)["percent"], 75.0)

    def test_without_plan_reports_stream_progress(self):
        self.assertEqual(OverallProgress().update("x", 5, 10, 0.5)["percent"], 50.0)


class CookieTests(unittest.TestCase):
    def test_netscape_format(self):
        text = to_netscape([
            {"name": "sid", "value": "abc", "domain": ".instagram.com", "path": "/", "secure": True,
             "hostOnly": False, "expirationDate": 1999999999.5},
            {"name": "host", "value": "x", "domain": "www.example.com", "hostOnly": True},
            {"name": "bad", "value": "a\tb", "domain": ".x.com"},
        ])
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "# Netscape HTTP Cookie File")
        self.assertEqual(lines[1], ".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsid\tabc")
        self.assertEqual(lines[2], "www.example.com\tFALSE\t/\tFALSE\t0\thost\tx")
        self.assertEqual(len(lines), 3)  # cookie with a tab is dropped


if __name__ == "__main__":
    unittest.main()


class InstagramStoryFallbackTest(unittest.TestCase):
    PAGE = ('<html><script type="application/json">{"require":[["x",{"data":'
            '{"xdt_api__v1__feed__reels_media":{"reels_media":[{"items":['
            '{"pk":"111","video_versions":[{"type":101,"url":"https://cdn/a.mp4"}]},'
            '{"pk":"222","video_duration":7.5,"user":{"full_name":"Some One"},'
            '"image_versions2":{"candidates":[{"url":"https://cdn/t.jpg"}]},'
            '"video_versions":[{"type":101,"url":"https://cdn/b.mp4","width":720,"height":1280}]},'
            '{"pk":"333","image_versions2":{"candidates":[{"url":"https://cdn/p.jpg"}]}}'
            ']}]}}}]]}</script></html>')
    URL = "https://www.instagram.com/stories/someone/222/"

    def setUp(self):
        try:
            from vidgrab import instagram
        except ImportError:
            self.skipTest("yt-dlp not installed")
        self.instagram = instagram

    def test_picks_story_by_id(self):
        info = self.instagram.parse_story_page(self.PAGE, "222", "someone", self.URL)
        self.assertEqual(info["id"], "222")
        self.assertEqual(info["formats"][0]["url"], "https://cdn/b.mp4")
        self.assertEqual(info["uploader"], "Some One")
        self.assertEqual(info["thumbnail"], "https://cdn/t.jpg")

    def test_defaults_to_first_story(self):
        info = self.instagram.parse_story_page(self.PAGE, None, "someone", self.URL)
        self.assertEqual(info["id"], "111")

    def test_photo_story_is_reported(self):
        with self.assertRaises(self.instagram.StoryError):
            self.instagram.parse_story_page(self.PAGE, "333", "someone", self.URL)

    def test_no_data(self):
        self.assertIsNone(self.instagram.parse_story_page("<html></html>", None, "x", self.URL))

    def test_story_url_detection(self):
        self.assertTrue(self.instagram.is_story_url(self.URL))
        self.assertTrue(self.instagram.is_story_url("https://www.instagram.com/stories/someone/"))
        self.assertFalse(self.instagram.is_story_url("https://www.instagram.com/stories/highlights/1/"))
        self.assertFalse(self.instagram.is_story_url("https://www.instagram.com/reel/abc/"))


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        try:
            from vidgrab import self_update
        except ImportError:
            self.skipTest("helper dependencies not installed")
        self.su = self_update

    def test_versions(self):
        self.assertEqual(self.su.parse_version("v1.2.3"), (1, 2, 3))
        self.assertTrue(self.su.is_newer("1.10.0", "1.9.9"))
        self.assertFalse(self.su.is_newer("v1.0.0", "1.0.0"))
        with self.assertRaises(self.su.UpdateError):
            self.su.parse_version("1.0.0-beta")

    def test_rejects_zip_slip(self):
        import tempfile
        import zipfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("repo/../../escaped.txt", "x")
            with self.assertRaises(self.su.UpdateError):
                self.su._extract(archive, Path(temp) / "out")

    def test_rejects_insecure_url(self):
        with self.assertRaises(self.su.UpdateError):
            self.su._open("http://example.com/update.zip", "application/zip")

    def test_rejects_different_extension_key(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as temp:
            installed, new = Path(temp) / "installed", Path(temp) / "new"
            for root, key in ((installed, "KEY-A"), (new, "KEY-B")):
                for name in ("installer/install.py", "helper/helper.py", "helper/vidgrab/__init__.py"):
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    (root / name).write_text("")
                (root / "extension").mkdir(exist_ok=True)
                (root / "extension/manifest.json").write_text(json.dumps({"key": key, "version": "2.0.0"}))
            with mock.patch.object(self.su, "HELPER_DIR", installed):
                with self.assertRaises(self.su.UpdateError):
                    self.su._verify(new, "2.0.0")
