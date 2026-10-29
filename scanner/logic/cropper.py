"""Crop a listing card out of a captured screenshot and name the file."""
import re
from datetime import datetime
from pathlib import Path

from PIL import Image

Box = tuple[int, int, int, int]  # left, top, right, bottom


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:max_len].strip("-")
    return slug or "unknown"


def crop_filename(when: datetime, skin: str, price: int, seller: str) -> str:
    name = f"{when:%Y%m%d_%H%M%S}__{slugify(skin)}__price-{price}"
    return name + (f"__{slugify(seller)}" if seller else "") + ".png"


def unique_path(path: Path) -> Path:
    n, p = 2, path
    while p.exists():
        p = path.with_stem(f"{path.stem}_{n}")
        n += 1
    return p


def crop_card(image: Image.Image, box: Box | None, pad: int = 4) -> tuple[Image.Image, str]:
    """Real pixels from the capture, never reconstructed.

    Status: "ok", "clamped" (card runs past the screenshot edge), or "fallback_full"
    (no usable box, so the whole screenshot is kept as evidence).
    """
    if box is None or box[2] <= box[0] or box[3] <= box[1]:
        return image.copy(), "fallback_full"
    w, h = image.size
    left, top, right, bottom = box
    clipped = left < 0 or top < 0 or right > w or bottom > h
    padded = (max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad))
    if padded[2] <= padded[0] or padded[3] <= padded[1]:
        return image.copy(), "fallback_full"
    return image.crop(padded), "clamped" if clipped else "ok"


def save_crop(image: Image.Image, box: Box | None, matches_dir: Path, root: Path,
              when: datetime, skin: str, price: int, seller: str) -> tuple[str, str]:
    """Save the crop; returns (path relative to root with forward slashes, crop status)."""
    crop, status = crop_card(image, box)
    matches_dir.mkdir(parents=True, exist_ok=True)
    path = unique_path(matches_dir / crop_filename(when, skin, price, seller))
    crop.save(path)
    try:
        return path.relative_to(root).as_posix(), status
    except ValueError:  # output folder is outside root: keep the full path
        return path.as_posix(), status
