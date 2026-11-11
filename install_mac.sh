#!/bin/bash
# VidGrab installer for macOS. Run once:  ./install_mac.sh
# Installs ffmpeg (via Homebrew), sets up the helper's venv and connects it to
# Chrome / Brave / Edge. Safe to re-run. Uninstall: ./install_mac.sh --uninstall
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" != "--uninstall" ]]; then
  echo "==> Checking system tools"
  if ! command -v brew >/dev/null 2>&1; then
    for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [[ -x "$p" ]] && eval "$("$p" shellenv)" && break
    done
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then brew install python
    else echo "Python 3 is missing. Run: xcode-select --install  (then re-run this script)"; exit 1; fi
  fi

  if ! command -v ffmpeg >/dev/null 2>&1 && [[ ! -x /opt/homebrew/bin/ffmpeg && ! -x /usr/local/bin/ffmpeg ]]; then
    if command -v brew >/dev/null 2>&1; then
      echo "    Installing ffmpeg with Homebrew…"
      brew install ffmpeg
    else
      echo "    ! Homebrew not found, so ffmpeg can't be installed automatically."
      echo "      Install Homebrew from https://brew.sh, then re-run this script."
    fi
  else
    echo "    ✓ ffmpeg"
  fi
fi

python3 installer/install.py "$@"
