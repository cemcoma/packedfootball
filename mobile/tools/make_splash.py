#!/usr/bin/env python3
"""Builds the splash assets under sprites/splash/ from title.png and
title_background.jpg. Re-run after changing either source.

    python3 mobile/tools/make_splash.py

Outputs:
  boot/boot_splash.png  engine boot splash (project.godot) + iOS launch image.
                        boot/ is .gdignore'd: the engine reads the PNG raw, so
                        importing it too would only ship a second 3 MB copy.
  splash_background.jpg the same backdrop without the logo, for Splash.tscn
  splash_logo.png       logo with a baked soft shadow, for Splash.tscn

The three share one geometry (W/H, LOGO_WIDTH_FRAC, LOGO_CENTER_Y_FRAC) so
Splash.tscn's first frame lines up exactly with the engine splash --
Splash.gd re-derives the logo placement from the same numbers.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

MOBILE = Path(__file__).resolve().parent.parent
SRC_BG = MOBILE / "sprites/backgrounds/title_background.jpg"
SRC_LOGO = MOBILE / "sprites/title.png"
OUT = MOBILE / "sprites/splash"
BOOT_DIR = OUT / "boot"

# Composition canvas. ~2.18:1 matches most current phones; boot_splash
# stretch_mode "cover" crops the sides on 16:9 / iPad, never letterboxes.
W, H = 2400, 1100
# Logo width as a fraction of W, and its centre as a fraction of H.
# Splash.gd uses the same two numbers.
LOGO_WIDTH_FRAC = 0.43
LOGO_CENTER_Y_FRAC = 0.46
# Transparent padding around the logo so the shadow isn't clipped.
LOGO_PAD = 90
SHADOW_BLUR = 34
SHADOW_OFFSET = (0, 14)
SHADOW_ALPHA = 150

EDGE = (13, 21, 38)  # vignette edge colour; also boot_splash/bg_color
EDGE_FLOOR = 0.32  # brightness kept at the very edge of the vignette


def cover_crop(im: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def build_background() -> Image.Image:
    bg = cover_crop(Image.open(SRC_BG).convert("RGB"), W, H)
    bg = ImageEnhance.Brightness(bg).enhance(0.86)

    # Elliptical vignette, built small and blurred so it's cheap and smooth.
    small = Image.new("L", (W // 8, H // 8), 0)
    sw, sh = small.size
    ImageDraw.Draw(small).ellipse((-sw * 0.05, -sh * 0.25, sw * 1.05, sh * 1.15), fill=255)
    small = small.filter(ImageFilter.GaussianBlur(sw * 0.16))
    vig = small.resize((W, H), Image.BILINEAR)
    vig = vig.point(lambda v: int(255 * (EDGE_FLOOR + (1 - EDGE_FLOOR) * v / 255)))

    # Bottom band so the loading bar / status text sit on something calm.
    band = Image.linear_gradient("L").resize((W, H))  # 0 at top -> 255 at bottom
    band = band.point(lambda v: int(255 * (1.0 - 0.5 * max(0.0, (v / 255 - 0.58) / 0.42))))

    mult = ImageChops.multiply(vig, band)
    edge = Image.new("RGB", (W, H), EDGE)
    return Image.composite(bg, edge, mult)


def build_logo() -> Image.Image:
    logo = Image.open(SRC_LOGO).convert("RGBA")
    w, h = logo.width + 2 * LOGO_PAD, logo.height + 2 * LOGO_PAD

    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    alpha = logo.getchannel("A").point(lambda v: v * SHADOW_ALPHA // 255)
    shadow.paste((0, 0, 0, 255), (LOGO_PAD + SHADOW_OFFSET[0], LOGO_PAD + SHADOW_OFFSET[1]), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(shadow)
    out.alpha_composite(logo, (LOGO_PAD, LOGO_PAD))
    return out


def main() -> None:
    BOOT_DIR.mkdir(parents=True, exist_ok=True)
    (BOOT_DIR / ".gdignore").touch()

    bg = build_background()
    bg.save(OUT / "splash_background.jpg", quality=88, optimize=True, progressive=True)

    logo = build_logo()
    logo.save(OUT / "splash_logo.png", optimize=True)

    # Composite exactly as Splash.gd lays it out: the padded logo scaled so
    # the logo itself (not the padding) spans LOGO_WIDTH_FRAC of the width.
    raw_logo_w = Image.open(SRC_LOGO).width
    scale = (W * LOGO_WIDTH_FRAC) / raw_logo_w
    lw, lh = round(logo.width * scale), round(logo.height * scale)
    placed = logo.resize((lw, lh), Image.LANCZOS)
    boot = bg.convert("RGBA")
    boot.alpha_composite(placed, (round(W / 2 - lw / 2), round(H * LOGO_CENTER_Y_FRAC - lh / 2)))
    boot.convert("RGB").save(BOOT_DIR / "boot_splash.png", optimize=True)

    for p in sorted(OUT.rglob("*")):
        if p.suffix in (".png", ".jpg"):
            print(f"{p.relative_to(MOBILE)}  {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
