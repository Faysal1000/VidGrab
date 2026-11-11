"""Write browser cookies (from chrome.cookies) into a Netscape cookie file for yt-dlp.

Cookies are only needed for logged-in content (e.g. Instagram, Facebook). The
file is created with owner-only permissions and deleted when the job ends.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator


def _line(cookie: dict[str, Any]) -> str | None:
    name = cookie.get("name")
    domain = cookie.get("domain")
    if not name or not domain:
        return None
    host_only = bool(cookie.get("hostOnly"))
    if host_only:
        domain = domain.lstrip(".")
    elif not domain.startswith("."):
        domain = "." + domain
    expiry = int(cookie.get("expirationDate") or 0)
    fields = [
        domain,
        "FALSE" if host_only else "TRUE",
        cookie.get("path") or "/",
        "TRUE" if cookie.get("secure") else "FALSE",
        str(expiry),
        name,
        cookie.get("value", ""),
    ]
    # Tabs/newlines would corrupt the file format.
    if any("\t" in f or "\n" in f for f in fields):
        return None
    return "\t".join(fields)


def to_netscape(cookies: list[dict[str, Any]]) -> str:
    lines = ["# Netscape HTTP Cookie File"]
    lines += [line for line in map(_line, cookies) if line]
    return "\n".join(lines) + "\n"


@contextmanager
def cookie_file(cookies: list[dict[str, Any]] | None) -> Iterator[str | None]:
    """Yield a temp cookie-file path (or None when there are no cookies)."""
    if not cookies:
        yield None
        return
    fd, path = tempfile.mkstemp(prefix="vidgrab-cookies-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(to_netscape(cookies))
        os.chmod(path, 0o600)
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


LOGIN_COOKIES = ("sessionid", "c_user", "auth_token", "SAPISID", "sid_tt")


def describe_cookies(cookies: list[dict[str, Any]] | None) -> str:
    """Log-safe summary: count and whether a login cookie is present (never values)."""
    if not cookies:
        return "no cookies"
    names = {c.get("name") for c in cookies}
    logged_in = any(name in names for name in LOGIN_COOKIES)
    return f"{len(cookies)} cookies, login cookie {'present' if logged_in else 'missing'}"
