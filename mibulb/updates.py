"""Check GitHub for a newer release, and install it.

Updating (installed copies only):
1. download MiBulb-Setup.exe from the release
2. check its SHA-256 against the hash GitHub publishes for the release
   asset (or SHA256SUMS.txt), so a corrupted or swapped file is never run
3. start it silently with /UPDATE; Mi Bulb then quits, the installer waits
   for it to close, installs, and starts Mi Bulb again

Portable and source copies can't update themselves; they get a link instead.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from . import __version__

REPO = "akanora/mibulb"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_NAME = "MiBulb-Setup.exe"


class UpdateError(Exception):
    pass


@dataclass
class Update:
    version: str
    url: str  # release page
    installer_url: str = ""
    installer_sha256: str = ""
    sums_url: str = ""


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
    if not tag or parse_version(tag) <= parse_version(current):
        return None
    update = Update(tag.lstrip("vV"), data.get("html_url", f"https://github.com/{REPO}/releases/latest"))
    for asset in data.get("assets", []):
        if asset.get("name") == INSTALLER_NAME:
            update.installer_url = asset.get("browser_download_url", "")
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                update.installer_sha256 = digest.split(":", 1)[1].lower()
        elif asset.get("name") == "SHA256SUMS.txt":
            update.sums_url = asset.get("browser_download_url", "")
    return update


def is_installed() -> bool:
    """True when running from the installer's copy (it can update itself)."""
    if not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).parent / "unins000.exe").exists()


def _expected_hash(update: Update, timeout: float) -> str:
    if update.installer_sha256:
        return update.installer_sha256
    if update.sums_url:
        response = requests.get(update.sums_url, timeout=timeout)
        response.raise_for_status()
        for line in response.text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == INSTALLER_NAME:
                return parts[0].lower()
    raise UpdateError("The release has no checksum for the installer, so it won't be installed.")


def download(update: Update, progress: Callable[[int], None] | None = None,
             folder: Path | None = None, timeout: float = 30) -> Path:
    """Download and verify the installer. Returns its path."""
    if not update.installer_url:
        raise UpdateError("This release has no installer to download.")
    expected = _expected_hash(update, timeout)
    folder = folder or Path(tempfile.gettempdir()) / "mibulb-update"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"MiBulb-Setup-{update.version}.exe"
    partial = target.with_suffix(".part")

    digest = hashlib.sha256()
    try:
        with requests.get(update.installer_url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last = -1
            with open(partial, "wb") as out:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    percent = done * 100 // total if total else 0
                    if progress and percent != last:
                        progress(percent)
                        last = percent
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc

    if digest.hexdigest() != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError("The downloaded installer didn't match its published checksum, so it was deleted.")
    partial.replace(target)
    return target


def installer_arguments(minimized: bool) -> str:
    args = "/SILENT /SUPPRESSMSGBOXES /NORESTART /SP- /UPDATE"
    if minimized:
        args += " /RELAUNCH=--minimized"
    return args


def launch_installer(path: Path, minimized: bool) -> None:
    """Start the installer. Raises OSError if it couldn't start (e.g. the admin prompt was cancelled)."""
    # ShellExecute (not CreateProcess) so Windows can show the admin prompt
    # for copies installed in Program Files.
    os.startfile(str(path), "open", installer_arguments(minimized))
