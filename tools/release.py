"""Bump VidGrab's version; GitHub Actions then publishes the release.

    python3 tools/release.py 1.1.0

Sets the version in extension/manifest.json and helper/vidgrab/__init__.py,
commits "Release v1.1.0" and pushes. The Release workflow
(.github/workflows/release.yml) runs the tests and creates tag v1.1.0 with its
GitHub Release. Installed copies then offer "Update". Commit your changes first.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "extension" / "manifest.json"
HELPER_INIT = ROOT / "helper" / "vidgrab" / "__init__.py"


def run(*command: str, capture: bool = False) -> str:
    result = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=capture)
    return (result.stdout or "").strip()


def parse(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"Version must look like 1.2.3 (got {version!r}).")
    return tuple(map(int, version.split(".")))


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    version = sys.argv[1].lstrip("v")
    current = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    if parse(version) <= parse(current):
        sys.exit(f"New version {version} must be higher than the current {current}.")
    if run("git", "status", "--porcelain", capture=True):
        sys.exit("You have uncommitted changes. Commit them first, then run this again.")

    MANIFEST.write_text(MANIFEST.read_text(encoding="utf-8").replace(
        f'"version": "{current}"', f'"version": "{version}"', 1), encoding="utf-8")
    HELPER_INIT.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"',
                                  HELPER_INIT.read_text(encoding="utf-8"), count=1), encoding="utf-8")
    if json.loads(MANIFEST.read_text(encoding="utf-8"))["version"] != version:
        sys.exit("Couldn't update the version in manifest.json.")

    run("git", "add", str(MANIFEST), str(HELPER_INIT))
    run("git", "commit", "-m", f"Release v{version}")
    run("git", "push", "origin", "HEAD")
    remote = run("git", "remote", "get-url", "origin", capture=True).removesuffix(".git")
    print(f"\nPushed v{version}. GitHub Actions will test it and publish the release:\n"
          f"  {remote}/actions")


if __name__ == "__main__":
    main()
