"""The Mi Bulb logo, drawn in code so the exe, window and tray icon always match.

Run tools/make_icon.py to regenerate assets/icon.ico and assets/logo.png.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

BACKGROUND = (35, 37, 44, 255)
GLASS_ON = (245, 197, 66, 255)
GLASS_OFF = (107, 109, 117, 255)
GLOW = (245, 197, 66)
METAL = (201, 203, 209, 255)
METAL_DARK = (154, 156, 165, 255)


def draw_logo(size: int = 256, on: bool = True) -> Image.Image:
    s = 1024  # draw large, then downsample for smooth edges
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BACKGROUND)

    cx, cy, r = s * 0.5, s * 0.42, s * 0.25

    if on:
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((cx - r * 1.45, cy - r * 1.45, cx + r * 1.45, cy + r * 1.45), fill=(*GLOW, 110))
        glow = glow.filter(ImageFilter.GaussianBlur(s * 0.06))
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255)
        image.paste(glow, (0, 0), Image.composite(glow, Image.new("RGBA", (s, s)), mask))
        draw = ImageDraw.Draw(image)

    glass = GLASS_ON if on else GLASS_OFF
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=glass)
    # neck tapering from the globe down to the base
    draw.polygon(
        [(cx - r * 0.62, cy + r * 0.78), (cx + r * 0.62, cy + r * 0.78), (cx + r * 0.44, s * 0.70), (cx - r * 0.44, s * 0.70)],
        fill=glass,
    )
    # highlight on the glass
    draw.arc((cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72), start=200, end=255,
             fill=(255, 255, 255, 170 if on else 90), width=int(s * 0.03))

    # screw base
    w = r * 0.5
    draw.rounded_rectangle((cx - w, s * 0.705, cx + w, s * 0.755), radius=s * 0.02, fill=METAL)
    draw.rounded_rectangle((cx - w, s * 0.77, cx + w, s * 0.82), radius=s * 0.02, fill=METAL)
    draw.rounded_rectangle((cx - w * 0.55, s * 0.835, cx + w * 0.55, s * 0.875), radius=s * 0.02, fill=METAL_DARK)

    return image.resize((size, size), Image.LANCZOS)


def save_ico(path: str) -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw_logo(256).save(path, format="ICO", sizes=[(n, n) for n in sizes])
