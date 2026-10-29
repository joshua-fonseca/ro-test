from datetime import datetime
from pathlib import Path

from PIL import Image

from scanner.logic.cropper import crop_card, crop_filename, save_crop, slugify, unique_path

WHEN = datetime(2026, 10, 28, 13, 5, 0)


def img(w=200, h=100):
    return Image.new("RGB", (w, h), "red")


def test_slugify():
    assert slugify("Nocturne Marlin [Rainbow]") == "nocturne-marlin-rainbow"
    assert slugify("Bob123") == "bob123"
    assert slugify("") == "unknown" and slugify("!!!") == "unknown"
    assert len(slugify("x" * 200)) == 40


def test_filename_format():
    assert crop_filename(WHEN, "Nocturne Marlin", 8700, "Bob123") == \
        "20261028_130500__nocturne-marlin__price-8700__bob123.png"


def test_crop_ok_adds_padding():
    crop, status = crop_card(img(), (50, 20, 150, 80), pad=4)
    assert status == "ok" and crop.size == (108, 68)


def test_crop_clamped_when_card_runs_past_edge():
    crop, status = crop_card(img(), (150, 20, 260, 80), pad=0)
    assert status == "clamped" and crop.size == (50, 60)


def test_fallback_to_full_screenshot():
    for box in (None, (10, 10, 10, 50), (500, 500, 600, 600)):
        crop, status = crop_card(img(), box)
        assert status == "fallback_full" and crop.size == (200, 100)


def test_crop_uses_real_pixels():
    base = img()
    base.putpixel((60, 30), (0, 255, 0))
    crop, _ = crop_card(base, (50, 20, 150, 80), pad=0)
    assert crop.getpixel((10, 10)) == (0, 255, 0)


def test_unique_path_never_overwrites(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"x")
    assert unique_path(p).name == "a_2.png"
    (tmp_path / "a_2.png").write_bytes(b"x")
    assert unique_path(p).name == "a_3.png"


def test_save_crop_returns_relative_posix_path(tmp_path):
    rel, status = save_crop(img(), (50, 20, 150, 80), tmp_path / "output/screenshots/matches", tmp_path,
                            WHEN, "Nocturne Marlin", 8700, "Bob123")
    assert rel == "output/screenshots/matches/20261028_130500__nocturne-marlin__price-8700__bob123.png"
    assert status == "ok" and (tmp_path / rel).exists()
    rel2, _ = save_crop(img(), None, tmp_path / "output/screenshots/matches", tmp_path,
                        WHEN, "Nocturne Marlin", 8700, "Bob123")
    assert rel2 != rel


def test_save_crop_outside_root_returns_full_path(tmp_path):
    root, elsewhere = tmp_path / "project", tmp_path / "elsewhere"
    root.mkdir()
    path, status = save_crop(img(), (50, 20, 150, 80), elsewhere, root, WHEN, "Skin", 100, "Bob")
    assert status == "ok" and Path(path).exists() and Path(path).is_absolute()
