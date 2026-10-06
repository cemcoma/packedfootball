#!/usr/bin/env python3
"""Builds the Android launcher icons and the Play Store listing graphics from
the iOS icon, title.png and the splash. Re-run after changing any of them.

    python3 mobile/tools/make_android_icons.py

Outputs (launcher, referenced by the Android preset in export_presets.cfg):
  sprites/icons/android/launcher_192.png        legacy launcher icon
  sprites/icons/android/adaptive_background.png 432x432, the title stadium, blurred
  sprites/icons/android/adaptive_foreground.png 432x432, the iOS icon art, feathered
  sprites/icons/android/adaptive_monochrome.png 432x432, logo plate with knocked-out
                                                letters, for Android 13 themed icons
Outputs (Play Console > Store listing, uploaded by hand, gitignored):
  build/play_store/icon_512.png                 full-bleed, Play rounds it itself
  build/play_store/feature_graphic_1024x500.png

Adaptive layers are 108dp of which launchers show the central 72dp (288 of
432 px), masked to anything from a circle to a squircle. ART_FRAC keeps the
logo plate's and the players' corners inside even the circle.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

MOBILE = Path(__file__).resolve().parent.parent
SRC_ICON = MOBILE / "sprites/icons/app_icon.png"
SRC_LOGO = MOBILE / "sprites/title.png"
SRC_STADIUM = MOBILE / "sprites/backgrounds/title_background.jpg"
SRC_SPLASH = MOBILE / "sprites/splash/boot/boot_splash.png"
OUT = MOBILE / "sprites/icons/android"
STORE_OUT = MOBILE / "build/play_store"

LAYER = 432
VISIBLE = 288
# The iOS art's width as a fraction of the visible 72dp.
ART_FRAC = 0.80
# Feather on the art's edge, as a fraction of its width; its stadium edge is
# already soft, so this blends it into the blurred copy behind.
FEATHER_FRAC = 0.06
BG_BLUR = 10
# Monochrome logo plate width as a fraction of the layer: inside the 66dp safe circle.
MONO_WIDTH_FRAC = 0.54
# A pixel this much more saturated (max-min channel) is a letter, not the plate.
LETTER_SAT = 60


def cover_crop(im: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def blurred_backdrop(size: int) -> Image.Image:
    stadium = cover_crop(Image.open(SRC_STADIUM).convert("RGB"), size, size)
    return stadium.filter(ImageFilter.GaussianBlur(BG_BLUR * size / LAYER))


def feathered(icon: Image.Image, size: int) -> Image.Image:
    art = icon.resize((size, size), Image.LANCZOS)
    feather = max(1, round(size * FEATHER_FRAC))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (feather, feather, size - feather, size - feather), radius=feather * 2, fill=255
    )
    mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))
    art.putalpha(ImageChops.multiply(art.getchannel("A"), mask))
    return art


def build_adaptive(icon: Image.Image) -> tuple[Image.Image, Image.Image]:
    background = blurred_backdrop(LAYER)
    art_size = round(VISIBLE * ART_FRAC)
    foreground = Image.new("RGBA", (LAYER, LAYER), (0, 0, 0, 0))
    offset = (LAYER - art_size) // 2
    foreground.alpha_composite(feathered(icon, art_size), (offset, offset))
    return background, foreground


def build_monochrome() -> Image.Image:
    logo = Image.open(SRC_LOGO).convert("RGBA")
    r, g, b, a = logo.split()
    sat = ImageChops.subtract(
        ImageChops.lighter(ImageChops.lighter(r, g), b), ImageChops.darker(ImageChops.darker(r, g), b)
    )
    letters = sat.point(lambda v: 255 if v > LETTER_SAT else 0).filter(ImageFilter.MedianFilter(3))
    plate = ImageChops.subtract(a, letters)

    w = round(LAYER * MONO_WIDTH_FRAC)
    h = round(logo.height * w / logo.width)
    plate = plate.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (LAYER, LAYER), (255, 255, 255, 0))
    out.paste((255, 255, 255, 255), ((LAYER - w) // 2, (LAYER - h) // 2), plate)
    return out


def build_store_icon(icon: Image.Image) -> Image.Image:
    # Play wants a full square; fill the iOS art's transparent corners.
    out = blurred_backdrop(512).convert("RGBA")
    out.alpha_composite(icon.resize((512, 512), Image.LANCZOS))
    return out.convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STORE_OUT.mkdir(parents=True, exist_ok=True)
    icon = Image.open(SRC_ICON).convert("RGBA")

    icon.resize((192, 192), Image.LANCZOS).save(OUT / "launcher_192.png", optimize=True)
    background, foreground = build_adaptive(icon)
    background.save(OUT / "adaptive_background.png", optimize=True)
    foreground.save(OUT / "adaptive_foreground.png", optimize=True)
    build_monochrome().save(OUT / "adaptive_monochrome.png", optimize=True)

    build_store_icon(icon).save(STORE_OUT / "icon_512.png", optimize=True)
    feature = cover_crop(Image.open(SRC_SPLASH).convert("RGB"), 1024, 500)
    feature.save(STORE_OUT / "feature_graphic_1024x500.png", optimize=True)

    for p in sorted([*OUT.glob("*.png"), *STORE_OUT.glob("*.png")]):
        print(f"{p.relative_to(MOBILE)}  {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
