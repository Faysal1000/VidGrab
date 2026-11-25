"""One-click VidGrab updates from the project's GitHub Releases.

The extension notices a newer release and asks the helper to install it. The
helper then:

  1. looks the release up on GitHub itself (it never trusts a download URL
     handed to it by the extension),
  2. downloads the release's source archive over HTTPS, with a size limit,
  3. unpacks it safely and checks it really is VidGrab (same extension key, so
     the same extension ID, and the version matches the release tag),
  4. runs that release's own installer in ``--update`` mode, which backs up
     the current files and restores them if anything goes wrong.

The extension reloads itself afterwards to pick up the new files.
"""

from __future__ import annotations

import json
import logging
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import UPDATE_REPO, __version__
from .environment import HELPER_DIR

log = logging.getLogger(__name__)

API_BASE = f"https://api.github.com/repos/{UPDATE_REPO}"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
INSTALL_TIMEOUT_S = 900
USER_AGENT = f"VidGrab-updater/{__version__}"

Progress = Callable[[dict[str, Any]], None]


class UpdateError(Exception):
    """Shown to the user as the reason the update didn't happen."""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Raises UpdateError for anything else."""
    cleaned = text.strip().lstrip("vV")
    parts = cleaned.split(".")
    if not 1 <= len(parts) <= 4 or not all(p.isdigit() for p in parts):
        raise UpdateError(f"Unrecognised version: {text!r}")
    return tuple(int(p) for p in parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_release() -> dict[str, Any]:
    release = _get_json(f"{API_BASE}/releases/latest")
    return _describe(release)


def apply_update(tag: str, progress: Progress) -> dict[str, Any]:
    release = _describe(_get_json(f"{API_BASE}/releases/tags/{urllib.parse.quote(tag, safe='')}"))
    if not is_newer(release["version"]):
        raise UpdateError(f"VidGrab {__version__} is already up to date.")
    log.info("Updating VidGrab %s -> %s", __version__, release["version"])

    with tempfile.TemporaryDirectory(prefix="vidgrab-update-") as temp:
        temp_dir = Path(temp)
        progress({"phase": "update", "stage": "downloading"})
        archive = _download(release["archive_url"], temp_dir / "release.zip")
        progress({"phase": "update", "stage": "checking"})
        root = _extract(archive, temp_dir / "src")
        _verify(root, release["version"])
        progress({"phase": "update", "stage": "installing"})
        _run_installer(root)

    log.info("VidGrab updated to %s", release["version"])
    return {"version": release["version"]}


# -- internals ----------------------------------------------------------------


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # installed with yt-dlp[default]

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url: str, accept: str):
    if urllib.parse.urlparse(url).scheme != "https":
        raise UpdateError("Refusing to download an update over an insecure connection.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        return urllib.request.urlopen(request, timeout=60, context=_ssl_context())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No VidGrab release found on GitHub.") from exc
        raise UpdateError(f"GitHub returned an error ({exc.code}). Try again later.") from exc
    except OSError as exc:
        raise UpdateError(f"Couldn't reach GitHub: {exc}") from exc


def _get_json(url: str) -> dict[str, Any]:
    with _open(url, "application/vnd.github+json") as response:
        return json.loads(response.read(2 * 1024 * 1024))


def _describe(release: dict[str, Any]) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "")
    archive = release.get("zipball_url")
    if not tag or not archive:
        raise UpdateError("The GitHub release is incomplete.")
    return {
        "tag": tag,
        "version": ".".join(map(str, parse_version(tag))),
        "notes": (release.get("body") or "")[:2000],
        "url": release.get("html_url"),
        "archive_url": archive,
    }


def _download(url: str, target: Path) -> Path:
    size = 0
    with _open(url, "application/zip") as response, target.open("wb") as handle:
        while chunk := response.read(256 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise UpdateError("The update download is unexpectedly large; stopped.")
            handle.write(chunk)
    return target


def _extract(archive: Path, target: Path) -> Path:
    """Unzip, refusing entries that would land outside ``target``."""
    target.mkdir()
    base = target.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                destination = (target / member.filename).resolve()
                if destination != base and base not in destination.parents:
                    raise UpdateError("The update archive contains unsafe paths; stopped.")
            bundle.extractall(target)
    except zipfile.BadZipFile as exc:
        raise UpdateError("The update download is damaged. Try again.") from exc
    # GitHub archives contain one top-level folder (owner-repo-sha/).
    entries = [p for p in target.iterdir() if p.is_dir()]
    return entries[0] if len(entries) == 1 else target


def _verify(root: Path, version: str) -> None:
    required = ["extension/manifest.json", "installer/install.py", "helper/helper.py",
                "helper/vidgrab/__init__.py"]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise UpdateError("The update is missing files: " + ", ".join(missing))
    installed_manifest = HELPER_DIR / "extension" / "manifest.json"
    if not installed_manifest.is_file():
        raise UpdateError("Updates only work for an installed copy of VidGrab.")
    new_manifest = json.loads((root / "extension/manifest.json").read_text(encoding="utf-8"))
    current_manifest = json.loads(installed_manifest.read_text(encoding="utf-8"))
    # The key fixes the extension ID; a different key would disconnect the helper.
    if new_manifest.get("key") != current_manifest.get("key"):
        raise UpdateError("The update doesn't match this VidGrab installation; stopped.")
    if parse_version(new_manifest.get("version", "0")) != parse_version(version):
        raise UpdateError("The update's version doesn't match its release tag; stopped.")


def _run_installer(root: Path) -> None:
    # -I: ignore env/user site; -X utf8: the installer prints ✓ even on Windows consoles.
    command = [sys.executable, "-I", "-X", "utf8", str(root / "installer" / "install.py"), "--update"]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=INSTALL_TIMEOUT_S, cwd=root,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("Installing the update took too long; the old version was kept.") from exc
    log.info("installer output:\n%s%s", proc.stdout, proc.stderr)
    if proc.returncode != 0:
        lines = [line.strip() for line in (proc.stderr or proc.stdout).splitlines() if line.strip()]
        raise UpdateError("Update failed and the old version was kept: "
                          + (lines[-1] if lines else "unknown error"))

