"""Cross-platform installer for the VidGrab helper (stdlib only).

Usually run through install_mac.sh / install_linux.sh / install_windows.bat,
which first install system packages (Python, ffmpeg). This script then:

  1. copies helper/ and extension/ to a per-user app-data folder (INSTALL_DIR)
  2. creates a venv there and installs yt-dlp + deno into it
  3. records where ffmpeg/deno live (config.json)
  4. registers the native-messaging host with every Chromium-based browser
     found (Chrome, Brave, Edge, Chromium, Vivaldi, Arc)

Why copy instead of running from this folder? macOS privacy protection stops
browsers from launching programs inside Desktop, Documents or Downloads, and
once installed, the downloaded folder can be moved or deleted freely.

Re-running it is safe (it also applies code updates). Use --uninstall to undo.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_HELPER_DIR = ROOT / "helper"
SOURCE_EXTENSION_DIR = ROOT / "extension"

HOST_NAME = "com.vidgrab.helper"  # keep in sync with extension/background/main.js
# Fixed by the "key" in extension/manifest.json, so it's the same in every browser.
EXTENSION_ID = "gafplimobpeodpgeiamfedbhoodklmem"

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def _install_dir() -> Path:
    if IS_WINDOWS:
        return Path(os.environ["LOCALAPPDATA"]) / "VidGrab"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "VidGrab"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "vidgrab"


INSTALL_DIR = _install_dir()
VENV_DIR = INSTALL_DIR / ".venv"
# Files copied from helper/ (the venv, logs and config.json are created in place).
HELPER_FILES = ("helper.py", "run_helper.sh", "run_helper.bat", "requirements.txt")
HELPER_PACKAGE = "vidgrab"
# The browser loads the extension from here ("Load unpacked").
EXTENSION_DIR = INSTALL_DIR / "extension"

# Per-user NativeMessagingHosts locations, relative to the browser's config dir.
MAC_BROWSERS = {
    "Google Chrome": "Google/Chrome",
    "Google Chrome Beta": "Google/Chrome Beta",
    "Google Chrome Canary": "Google/Chrome Canary",
    "Brave": "BraveSoftware/Brave-Browser",
    "Microsoft Edge": "Microsoft Edge",
    "Chromium": "Chromium",
    "Vivaldi": "Vivaldi",
    "Arc": "Arc/User Data",
}
LINUX_BROWSERS = {
    "Google Chrome": "google-chrome",
    "Google Chrome Beta": "google-chrome-beta",
    "Brave": "BraveSoftware/Brave-Browser",
    "Microsoft Edge": "microsoft-edge",
    "Chromium": "chromium",
    "Vivaldi": "vivaldi",
}
WINDOWS_REGISTRY_KEYS = {
    "Google Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "Brave": r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    "Microsoft Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "Chromium": r"Software\Chromium\NativeMessagingHosts",
}


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def ok(message: str) -> None:
    print(f"    ✓ {message}", flush=True)


def warn(message: str) -> None:
    print(f"    ! {message}", flush=True)


# ---------------------------------------------------------------------------
# 1. Copy files
# ---------------------------------------------------------------------------

def _replace_tree(source: Path, target: Path) -> None:
    """Copy a directory, removing the old copy first so deleted files don't linger."""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))


def copy_files() -> None:
    step(f"Installing VidGrab to {INSTALL_DIR}")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    for name in HELPER_FILES:
        shutil.copy2(SOURCE_HELPER_DIR / name, INSTALL_DIR / name)
    _replace_tree(SOURCE_HELPER_DIR / HELPER_PACKAGE, INSTALL_DIR / HELPER_PACKAGE)
    ok("Helper copied")
    _replace_tree(SOURCE_EXTENSION_DIR, EXTENSION_DIR)
    ok("Extension copied")


# ---------------------------------------------------------------------------
# 2. Virtual environment
# ---------------------------------------------------------------------------

def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def setup_venv() -> None:
    step("Setting up Python environment")
    if sys.version_info < (3, 9):
        sys.exit(f"Python 3.9+ is required (found {sys.version.split()[0]}).")
    if not venv_python().exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
        ok("Created virtual environment")
    python = str(venv_python())
    pip_env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    subprocess.run([python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True, env=pip_env)
    subprocess.run([python, "-m", "pip", "install", "--quiet", "--upgrade",
                    "-r", str(INSTALL_DIR / "requirements.txt")], check=True, env=pip_env)
    version = subprocess.run([python, "-c", "import yt_dlp; print(yt_dlp.version.__version__)"],
                             capture_output=True, text=True, check=True).stdout.strip()
    ok(f"yt-dlp {version} installed")


# ---------------------------------------------------------------------------
# 3. External tools
# ---------------------------------------------------------------------------

def _first_existing(candidates: list[str]) -> str | None:
    for candidate in candidates:
        for match in sorted(glob.glob(candidate), reverse=True):
            if os.path.isfile(match):
                return match
    return None


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        return _first_existing([
            rf"{local}\Microsoft\WinGet\Links\ffmpeg.exe",
            rf"{local}\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            rf"{os.environ.get('ProgramFiles', '')}\ffmpeg\bin\ffmpeg.exe",
        ])
    return _first_existing(["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"])


def find_deno() -> str | None:
    in_venv = VENV_DIR / ("Scripts/deno.exe" if IS_WINDOWS else "bin/deno")
    if in_venv.exists():
        return str(in_venv)
    return shutil.which("deno")


def write_config() -> None:
    step("Locating ffmpeg and deno")
    config = {"ffmpeg": find_ffmpeg(), "deno": find_deno()}
    for name, path in config.items():
        if path:
            ok(f"{name}: {path}")
        else:
            warn(f"{name} not found")
    if not config["ffmpeg"]:
        warn("ffmpeg is required to merge video+audio and convert formats.")
        warn("Install it (Mac: brew install ffmpeg · Linux: sudo apt install ffmpeg ·"
             " Windows: winget install Gyan.FFmpeg) and run this installer again.")
    (INSTALL_DIR / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. Native-messaging registration
# ---------------------------------------------------------------------------

def launcher_path() -> Path:
    launcher = INSTALL_DIR / ("run_helper.bat" if IS_WINDOWS else "run_helper.sh")
    if not IS_WINDOWS:
        launcher.chmod(0o755)
    return launcher


def host_manifest() -> dict:
    return {
        "name": HOST_NAME,
        "description": "VidGrab download helper (yt-dlp bridge)",
        "path": str(launcher_path()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }


def _posix_targets() -> dict[str, Path]:
    if IS_MAC:
        base, browsers = Path.home() / "Library" / "Application Support", MAC_BROWSERS
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        browsers = LINUX_BROWSERS
    # Only browsers that have been run at least once (their profile dir exists).
    return {name: base / rel / "NativeMessagingHosts"
            for name, rel in browsers.items() if (base / rel).is_dir()}


def register() -> None:
    step("Connecting the helper to your browsers")
    manifest = json.dumps(host_manifest(), indent=2)

    if IS_WINDOWS:
        import winreg

        manifest_path = INSTALL_DIR / f"{HOST_NAME}.json"
        manifest_path.write_text(manifest, encoding="utf-8")
        for browser, key in WINDOWS_REGISTRY_KEYS.items():
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{key}\{HOST_NAME}") as handle:
                winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, str(manifest_path))
            ok(browser)
        return

    targets = _posix_targets()
    if not targets:
        warn("No supported browser profile found. Open Chrome or Brave once, then re-run the installer.")
        return
    for browser, directory in targets.items():
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{HOST_NAME}.json").write_text(manifest, encoding="utf-8")
        ok(browser)


def unregister() -> None:
    step("Removing browser registrations")
    if IS_WINDOWS:
        import winreg

        for browser, key in WINDOWS_REGISTRY_KEYS.items():
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{key}\{HOST_NAME}")
                ok(browser)
            except FileNotFoundError:
                pass
        return
    for browser, directory in _posix_targets().items():
        manifest = directory / f"{HOST_NAME}.json"
        if manifest.exists():
            manifest.unlink()
            ok(browser)


# ---------------------------------------------------------------------------
# 5. Self-test
# ---------------------------------------------------------------------------

def self_test() -> bool:
    """Start the helper exactly like the browser would and send a ping."""
    step("Testing the helper")
    import struct

    request = json.dumps({"id": "selftest", "cmd": "ping"}).encode()
    command = ["cmd", "/c", str(launcher_path())] if IS_WINDOWS else [str(launcher_path())]
    try:
        proc = subprocess.run(command, input=struct.pack("<I", len(request)) + request,
                              capture_output=True, timeout=60)
        length = struct.unpack("<I", proc.stdout[:4])[0]
        reply = json.loads(proc.stdout[4:4 + length])
        data = reply["data"]
    except Exception as exc:  # report anything — this is a diagnostic
        warn(f"Helper did not respond correctly: {exc}")
        return False
    ok(f"Helper OK — yt-dlp {data['ytdlp_version']}, ffmpeg {'✓' if data['ffmpeg'] else '✗'},"
       f" deno {'✓' if data['deno'] else '✗'}")
    return True


def copy_to_clipboard(text: str) -> bool:
    commands = ([["clip"]] if IS_WINDOWS else [["pbcopy"]] if IS_MAC
                else [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]])
    for command in commands:
        if shutil.which(command[0]):
            try:
                subprocess.run(command, input=text.encode("utf-16" if IS_WINDOWS else "utf-8"),
                               check=True, timeout=5)
                return True
            except (subprocess.SubprocessError, OSError):
                continue
    return False


# The extension folder is inside a hidden folder, so explain how to paste the path.
_PASTE_HINT = {
    "darwin": "In the folder picker press  Cmd + Shift + G , paste (Cmd + V), press Return, then click Select.",
    "win32": "In the folder picker click the address bar at the top, paste (Ctrl + V), press Enter, then click Select Folder.",
}
_PASTE_HINT_LINUX = "In the folder picker press  Ctrl + L , paste (Ctrl + V), press Enter, then click Select/Open."


def print_next_steps(updated: bool) -> None:
    copied = copy_to_clipboard(str(EXTENSION_DIR))
    hint = _PASTE_HINT.get(sys.platform, _PASTE_HINT_LINUX)
    if updated:
        print(f"""
==> Updated! In each browser open the extensions page and click the reload
    button (↻) on the VidGrab card. That's it.

    (Adding VidGrab to another browser? Use "Load unpacked" with this folder:
     {EXTENSION_DIR}
     {"— copied to your clipboard. " if copied else ""}{hint})
""")
        return
    print(f"""
==> Almost done! Now add the extension to your browser (once per browser):

    1. Open  chrome://extensions   (Brave: brave://extensions · Edge: edge://extensions)
    2. Turn on "Developer mode" (switch in the top-right corner)
    3. Click "Load unpacked" and choose this folder:

         {EXTENSION_DIR}
{"         (already copied to your clipboard)" if copied else ""}
       {hint}
    4. Quit the browser completely and open it again.

    You can now delete the folder you downloaded — VidGrab runs from the folder above.
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true", help="remove browser registrations")
    args = parser.parse_args()

    if args.uninstall:
        unregister()
        if INSTALL_DIR.exists():
            shutil.rmtree(INSTALL_DIR)
            ok(f"Removed {INSTALL_DIR}")
        print("\nDone. Also remove VidGrab from your browser's extensions page.")
        return

    already_installed = (EXTENSION_DIR / "manifest.json").exists()
    copy_files()
    setup_venv()
    write_config()
    register()
    self_test()
    print_next_steps(updated=already_installed)


if __name__ == "__main__":
    main()
