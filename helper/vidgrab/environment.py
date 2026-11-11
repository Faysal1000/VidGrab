"""Locating external tools (ffmpeg, deno) and helper configuration.

Browsers launched from the Dock / Start menu often have a minimal PATH that
does not include Homebrew or user-level install locations, so we both read the
paths the installer recorded in config.json and extend PATH with the usual
locations as a fallback.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

HELPER_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = HELPER_DIR / "config.json"
LOG_DIR = HELPER_DIR / "logs"

_EXTRA_PATHS_POSIX = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/snap/bin",
    str(Path.home() / ".deno" / "bin"),
    str(Path.home() / ".local" / "bin"),
]
_EXTRA_PATHS_WINDOWS = [
    str(Path.home() / ".deno" / "bin"),
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"),
]


@dataclass(frozen=True)
class Tools:
    ffmpeg: str | None
    deno: str | None


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _extend_path() -> None:
    extras = _EXTRA_PATHS_WINDOWS if sys.platform == "win32" else _EXTRA_PATHS_POSIX
    current = os.environ.get("PATH", "").split(os.pathsep)
    additions = [p for p in extras if p and p not in current and os.path.isdir(p)]
    if additions:
        os.environ["PATH"] = os.pathsep.join(current + additions)


def _venv_binary(name: str) -> str | None:
    """Tools pip-installed into the helper's own venv (deno ships this way)."""
    venv = HELPER_DIR / ".venv"
    path = venv / "Scripts" / f"{name}.exe" if sys.platform == "win32" else venv / "bin" / name
    return str(path) if path.is_file() else None


def _resolve(configured: str | None, name: str) -> str | None:
    if configured and os.path.isfile(configured):
        return configured
    return _venv_binary(name) or shutil.which(name)


def discover_tools() -> Tools:
    _extend_path()
    config = _load_config()
    return Tools(
        ffmpeg=_resolve(config.get("ffmpeg"), "ffmpeg"),
        deno=_resolve(config.get("deno"), "deno"),
    )


def default_download_dir() -> Path:
    return Path.home() / "Downloads"


def resolve_download_dir(requested: str | None) -> Path:
    """Use the user's chosen folder if valid, otherwise ~/Downloads."""
    if requested and requested.strip():
        path = Path(os.path.expandvars(requested.strip())).expanduser()
        if not path.is_absolute():
            raise ValueError(f"Download folder must be an absolute path: {requested}")
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = default_download_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
