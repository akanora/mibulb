"""Check GitHub for a newer release."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from . import __version__

REPO = "akanora/mibulb"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


@dataclass
class Update:
    version: str
    url: str


def parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check(current: str = __version__, timeout: float = 10) -> Update | None:
    """Return the newest release if it's newer than the running version."""
    response = requests.get(LATEST_URL, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    response.raise_for_status()
    data = response.json()
    tag = data.get("tag_name", "")
    if tag and parse_version(tag) > parse_version(current):
        return Update(tag.lstrip("vV"), data.get("html_url", f"https://github.com/{REPO}/releases/latest"))
    return None
