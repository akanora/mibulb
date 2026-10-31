"""Regenerate assets/icon.ico (for the exe) and assets/logo.png (for the README)."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mibulb.icon import draw_logo, save_ico  # noqa: E402

assets = ROOT / "assets"
assets.mkdir(exist_ok=True)
save_ico(str(assets / "icon.ico"))
draw_logo(512).save(assets / "logo.png")
print(f"Wrote {assets / 'icon.ico'} and {assets / 'logo.png'}")
