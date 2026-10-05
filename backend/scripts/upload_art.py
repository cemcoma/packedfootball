"""Ships a new card type or pack art without an app update.

Converts the image to WebP at the bundled art's size, uploads it to
Firebase Storage under a content-hashed name, and writes the Firestore doc
the backend reads (services/remote_art.py, cached 5 minutes):

    card <tier>        -> card_types/<tier>  {family, range, url, sha256, bytes, text_color?}
    pack <sprite_key>  -> pack_art/<key>     {url, sha256, bytes}

A card tier is "<existing family>_<variant>" (special_toty, gold_rttk); a
static tier (gold, special_champ...) is a re-skin and keeps its own range.
Never delete a card_types doc: cards of that tier exist forever.

Usage:
    python3 backend/scripts/upload_art.py card special_toty toty.png --range 87 90 [--text-color "#ffffff"]
    python3 backend/scripts/upload_art.py pack TOTYPack toty_pack.png
    common: [--quality 90 | --lossless] [--preview out.webp] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
from pathlib import Path
from urllib.parse import quote

import firebase_admin
from firebase_admin import firestore, storage
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packedfootball"))
import config  # noqa: E402
from engine import TIER_RANGES, tier_family  # noqa: E402
from services.remote_art import FAMILIES  # noqa: E402

# The bundled art's sizes (mobile/sprites/player_cards, mobile/sprites/packs).
SIZES = {"card": (440, 600), "pack": (600, 800)}
COLLECTIONS = {"card": "card_types", "pack": "pack_art"}
FOLDERS = {"card": "card_art", "pack": "pack_art"}
CACHE_CONTROL = "public, max-age=31536000, immutable"

TIER_RE = re.compile(r"^[a-z]+_[a-z0-9]+$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def encode(path: Path, size: tuple[int, int], quality: int, lossless: bool) -> bytes:
    image = Image.open(path).convert("RGBA")
    w, h = image.size
    if abs(w / h - size[0] / size[1]) > 0.01:
        raise SystemExit(f"{path} is {w}x{h}; it needs the {size[0]}:{size[1]} aspect ratio")
    if image.size != size:
        image = image.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    if lossless:
        image.save(buf, "WEBP", lossless=True, method=6)
    else:
        image.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def download_url(bucket: str, object_path: str) -> str:
    # Public through storage.rules, so no token is needed.
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{quote(object_path, safe='')}?alt=media"


def card_fields(args, existing: dict) -> dict:
    tier = args.key
    if not (tier in TIER_RANGES or TIER_RE.match(tier)):
        raise SystemExit(f"{tier!r} is not <family>_<variant> (lowercase, e.g. special_toty)")
    if tier_family(tier) not in FAMILIES:
        raise SystemExit(f"unknown family {tier_family(tier)!r}; must be one of {sorted(FAMILIES)}")
    fields = {"family": tier_family(tier)}
    if tier not in TIER_RANGES:
        rng = args.range or existing.get("range")
        if not rng:
            raise SystemExit("a new card type needs --range LO HI")
        lo, hi = int(rng[0]), int(rng[1])
        if lo >= hi:
            raise SystemExit(f"--range {lo} {hi}: LO must be below HI")
        fields["range"] = [lo, hi]
    elif args.range:
        print(f"  note: {tier} is a static tier, so --range is ignored (re-skin only)")
    color = None if args.no_text_color else (args.text_color or existing.get("text_color"))
    if color:
        if not COLOR_RE.match(color):
            raise SystemExit(f"--text-color {color!r}: use #rrggbb")
        fields["text_color"] = color
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(SIZES))
    parser.add_argument("key", help="card: the tier (special_toty); pack: the pack doc's sprite_key")
    parser.add_argument("image", type=Path)
    parser.add_argument("--range", nargs=2, type=int, metavar=("LO", "HI"), help="card: the overall range")
    parser.add_argument("--text-color", help="card: label colour on light art, #rrggbb")
    parser.add_argument("--no-text-color", action="store_true", help="card: clear a previous --text-color")
    parser.add_argument("--quality", type=int, default=90, help="WebP quality (default 90)")
    parser.add_argument("--lossless", action="store_true", help="Lossless WebP (several times larger)")
    parser.add_argument("--preview", type=Path, help="Also write the converted WebP here, to eyeball it")
    parser.add_argument("--dry-run", action="store_true", help="Convert and report only, upload nothing")
    args = parser.parse_args()

    if args.kind == "pack" and not KEY_RE.match(args.key):
        raise SystemExit(f"sprite_key {args.key!r}: letters, digits, _ and - only")

    firebase_admin.initialize_app(options={"projectId": config.FIREBASE_PROJECT_ID, "storageBucket": config.ART_BUCKET})
    doc_ref = firestore.client().collection(COLLECTIONS[args.kind]).document(args.key)
    snap = doc_ref.get()
    existing = snap.to_dict() if snap.exists else {}

    fields = card_fields(args, existing) if args.kind == "card" else {}
    data = encode(args.image, SIZES[args.kind], args.quality, args.lossless)
    sha256 = hashlib.sha256(data).hexdigest()
    object_path = f"{FOLDERS[args.kind]}/{args.key}.{sha256[:12]}.webp"
    url = download_url(config.ART_BUCKET, object_path)
    doc = {**fields, "url": url, "sha256": sha256, "bytes": len(data)}

    print(f"{args.image}: {args.image.stat().st_size / 1024:.0f} KB -> {len(data) / 1024:.1f} KB WebP")
    print(f"  {config.ART_BUCKET}/{object_path}")
    print(f"  {COLLECTIONS[args.kind]}/{args.key}: {'replacing' if snap.exists else 'new'}")
    for k, v in doc.items():
        print(f"    {k}: {v}")
    if args.preview:
        args.preview.write_bytes(data)
        print(f"  preview written to {args.preview}")
    if existing.get("sha256") == sha256 and {k: existing.get(k) for k in doc} == doc:
        print("Unchanged, nothing to do.")
        return 0
    if args.dry_run:
        print("Dry run, nothing changed.")
        return 0

    blob = storage.bucket().blob(object_path)
    if not blob.exists():
        blob.cache_control = CACHE_CONTROL
        blob.upload_from_string(data, content_type="image/webp")
    doc_ref.set({**doc, "updated_at": firestore.SERVER_TIMESTAMP})
    print("Uploaded. Live for players within 5 minutes (at once for a pack open).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
