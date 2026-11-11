#!/bin/bash
# VidGrab installer for Linux. Run once:  ./install_linux.sh
# Installs python3-venv + ffmpeg with your package manager, sets up the helper's
# venv and connects it to Chrome / Brave / Edge / Chromium. Safe to re-run.
# Uninstall: ./install_linux.sh --uninstall
set -euo pipefail
cd "$(dirname "$0")"

install_pkgs() {
  if command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y python3 python3-venv ffmpeg
  elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y python3 ffmpeg
  elif command -v pacman >/dev/null 2>&1; then sudo pacman -S --needed --noconfirm python ffmpeg
  elif command -v zypper >/dev/null 2>&1; then sudo zypper install -y python3 ffmpeg
  else echo "    ! Unknown package manager — please install python3 (with venv) and ffmpeg yourself."
  fi
}

if [[ "${1:-}" != "--uninstall" ]]; then
  echo "==> Checking system tools"
  if ! command -v python3 >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1 \
     || ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    echo "    Installing python3 / ffmpeg (may ask for your password)…"
    install_pkgs
  else
    echo "    ✓ python3, ffmpeg"
  fi
fi

python3 installer/install.py "$@"
