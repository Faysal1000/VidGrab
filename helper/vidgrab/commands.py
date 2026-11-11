"""Command dispatcher: maps messages from the extension to actions.

Request:   {"id": "<request id>", "cmd": "<name>", ...params}
Responses: {"id": ..., "type": "result", "data": {...}}
           {"id": ..., "type": "error", "error": "<message>"}
           {"id": ..., "type": "progress", "data": {...}}   (downloads only)

Slow commands run on worker threads so the extension can cancel a download
or start another one while the first is still running.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yt_dlp

from . import __version__
from .environment import HELPER_DIR, Tools, discover_tools, resolve_download_dir
from .protocol import MessageWriter
from .ytdlp_runner import DownloadJob, FetchError, JobCancelled, fetch_info

log = logging.getLogger("vidgrab.commands")

Handler = Callable[[str, dict[str, Any]], None]


class CommandError(Exception):
    pass


def _validate_url(url: Any) -> str:
    if not isinstance(url, str):
        raise CommandError("Missing URL")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise CommandError("Only http(s) pages can be downloaded")
    return url


class Dispatcher:
    def __init__(self, writer: MessageWriter) -> None:
        self._writer = writer
        self._tools: Tools = discover_tools()
        self._jobs: dict[str, DownloadJob] = {}
        self._jobs_lock = threading.Lock()
        self._handlers: dict[str, tuple[Handler, bool]] = {
            # name: (handler, run_in_thread)
            "ping": (self._ping, False),
            "info": (self._info, True),
            "download": (self._download, True),
            "cancel": (self._cancel, False),
            "reveal": (self._reveal, False),
            "update": (self._update, True),
        }

    # -- plumbing -------------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id", ""))
        entry = self._handlers.get(str(message.get("cmd")))
        if entry is None:
            self._error(request_id, f"Unknown command: {message.get('cmd')!r}")
            return
        handler, threaded = entry
        if threaded:
            threading.Thread(target=self._safe_call, args=(handler, request_id, message),
                             daemon=True).start()
        else:
            self._safe_call(handler, request_id, message)

    def _safe_call(self, handler: Handler, request_id: str, message: dict[str, Any]) -> None:
        try:
            handler(request_id, message)
        except (CommandError, FetchError, ValueError) as exc:
            self._error(request_id, str(exc))
        except Exception as exc:  # never let one bad request kill the helper
            log.exception("Unhandled error in %s", message.get("cmd"))
            self._error(request_id, f"Unexpected error: {exc}")

    def _result(self, request_id: str, data: dict[str, Any]) -> None:
        self._writer.send({"id": request_id, "type": "result", "data": data})

    def _error(self, request_id: str, error: str) -> None:
        self._writer.send({"id": request_id, "type": "error", "error": error})

    def _progress(self, request_id: str, data: dict[str, Any]) -> None:
        self._writer.send({"id": request_id, "type": "progress", "data": data})

    def cancel_all(self) -> int:
        """Cancel running downloads (the browser went away). Returns how many."""
        with self._jobs_lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        return len(jobs)

    def wait_for_jobs(self, timeout: float) -> None:
        """Give cancelled jobs a moment to delete their partial files."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._jobs_lock:
                if not self._jobs:
                    return
            time.sleep(0.1)

    # -- commands -------------------------------------------------------------

    def _ping(self, request_id: str, _message: dict[str, Any]) -> None:
        self._result(request_id, {
            "helper_version": __version__,
            "ytdlp_version": yt_dlp.version.__version__,
            "ffmpeg": bool(self._tools.ffmpeg),
            "deno": bool(self._tools.deno),
            "python": sys.version.split()[0],
            "platform": sys.platform,
        })

    def _info(self, request_id: str, message: dict[str, Any]) -> None:
        urls = [_validate_url(u) for u in message.get("urls") or [] if u]
        if not urls:
            raise CommandError("No video URL provided")
        self._result(request_id, fetch_info(urls, self._tools, message.get("cookies")))

    def _download(self, request_id: str, message: dict[str, Any]) -> None:
        choice = message.get("choice")
        if not isinstance(choice, dict):
            raise CommandError("Missing download choice")
        job = DownloadJob(
            job_id=request_id,
            url=_validate_url(message.get("url")),
            choice=choice,
            output_dir=resolve_download_dir(message.get("output_dir")),
            cookies=message.get("cookies"),
            playlist=bool(choice.get("playlist")),
        )
        with self._jobs_lock:
            self._jobs[request_id] = job
        log.info("Job %s started: %s %s -> %s", request_id, job.url, choice, job.output_dir)
        try:
            result = job.run(self._tools, lambda data: self._progress(request_id, data))
            log.info("Job %s finished: %s", request_id, result["files"])
            self._result(request_id, result)
        except JobCancelled:
            log.info("Job %s cancelled", request_id)
            self._result(request_id, {"cancelled": True})
        except Exception as exc:
            log.warning("Job %s failed: %s", request_id, exc)
            raise
        finally:
            with self._jobs_lock:
                self._jobs.pop(request_id, None)

    def _cancel(self, request_id: str, message: dict[str, Any]) -> None:
        with self._jobs_lock:
            job = self._jobs.get(str(message.get("job_id")))
        if job:
            job.cancel()
        self._result(request_id, {"cancelled": bool(job)})

    def _reveal(self, request_id: str, message: dict[str, Any]) -> None:
        path = Path(str(message.get("path", "")))
        if not path.is_absolute() or not path.exists():
            raise CommandError("File no longer exists")
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        self._result(request_id, {"ok": True})

    def _update(self, request_id: str, _message: dict[str, Any]) -> None:
        """Upgrade yt-dlp (and deno) inside this venv. Takes effect when the helper restarts."""
        requirements = HELPER_DIR / "requirements.txt"
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "-r", str(requirements)],
            capture_output=True, text=True, timeout=600,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )
        if proc.returncode != 0:
            log.error("pip upgrade failed: %s", proc.stderr)
            raise CommandError("Update failed: " + (proc.stderr.strip().splitlines() or ["unknown error"])[-1])
        version = subprocess.run(
            [sys.executable, "-c", "import yt_dlp; print(yt_dlp.version.__version__)"],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        self._result(request_id, {
            "previous_version": yt_dlp.version.__version__,
            "ytdlp_version": version,
            "restart_required": version != yt_dlp.version.__version__,
        })
