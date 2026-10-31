"""Write winget manifests for a published release, ready to submit to microsoft/winget-pkgs.

    python tools/winget_manifest.py 0.10.0

Reads the release from GitHub (installer URL and SHA-256) and writes
packaging/winget/<version>/*.yaml. Check them with `winget validate`, then
submit with `wingetcreate submit` (see docs/PUBLISHING.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import urlopen

REPO = "akanora/mibulb"
PACKAGE = "akanora.MiBulb"
PRODUCT_CODE = "{2A6700FD-B38A-43AB-9AB8-3CA82B93A8F6}_is1"  # AppId from installer/mibulb.iss
ROOT = Path(__file__).resolve().parent.parent


def release(version: str) -> dict:
    with urlopen(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}", timeout=20) as response:
        return json.load(response)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    version = sys.argv[1].lstrip("v")
    data = release(version)
    setup = next((a for a in data["assets"] if a["name"] == "MiBulb-Setup.exe"), None)
    if setup is None or not str(setup.get("digest", "")).startswith("sha256:"):
        raise SystemExit("The release has no MiBulb-Setup.exe with a SHA-256 digest yet")
    sha256 = setup["digest"].split(":", 1)[1].upper()
    out = ROOT / "packaging" / "winget" / version
    out.mkdir(parents=True, exist_ok=True)
    header = "# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.1.6.0.schema.json\n\n"
    files = {
        f"{PACKAGE}.yaml": header.format(kind="version") + f"""PackageIdentifier: {PACKAGE}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
""",
        f"{PACKAGE}.installer.yaml": header.format(kind="installer") + f"""PackageIdentifier: {PACKAGE}
PackageVersion: {version}
InstallerType: inno
Scope: user
InstallModes:
  - interactive
  - silent
UpgradeBehavior: install
Installers:
  - Architecture: x64
    InstallerUrl: {setup["browser_download_url"]}
    InstallerSha256: {sha256}
    # Inno Setup's uninstall entry is the AppId plus "_is1"; it lets winget find and upgrade installs
    ProductCode: "{PRODUCT_CODE}"
ManifestType: installer
ManifestVersion: 1.6.0
""",
        f"{PACKAGE}.locale.en-US.yaml": header.format(kind="defaultLocale") + f"""PackageIdentifier: {PACKAGE}
PackageVersion: {version}
PackageLocale: en-US
Publisher: Ayberk Alcan
PublisherUrl: https://github.com/akanora
PackageName: Mi Bulb
PackageUrl: https://github.com/{REPO}
License: MIT
LicenseUrl: https://github.com/{REPO}/blob/main/LICENSE
ShortDescription: Control Xiaomi Mi Smart LED bulbs from Windows over your local network.
Description: >-
  Mi Bulb controls Mi Smart LED Bulb Essential (and other Yeelight/MIoT) bulbs from Windows: a window,
  tray quick panel, keyboard shortcuts, scenes, effects, schedules, screen and music sync. It signs in
  with a QR code to fetch the bulb's token, then talks to the bulb only on your local network.
Tags:
  - xiaomi
  - yeelight
  - smart-bulb
  - smart-home
  - lights
ReleaseNotesUrl: {data["html_url"]}
ManifestType: defaultLocale
ManifestVersion: 1.6.0
""",
    }
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"Wrote {len(files)} files to {out}")


if __name__ == "__main__":
    main()
