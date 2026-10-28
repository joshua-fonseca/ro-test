import csv
import glob
from datetime import datetime, timezone

import pytest

cv2 = pytest.importorskip("cv2")
from models import Target  # noqa: E402
from scan_once import scan_visible  # noqa: E402
from storage import Store  # noqa: E402

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)


def test_visible_cards_are_matched_cropped_and_logged(tmp_path, monkeypatch):
    files = glob.glob("sniper_arena_scanner_handoff/scroll_starveil_f02.png")
    if not files:
        pytest.skip("fixture screenshots missing")
    img = cv2.imread(files[0])  # complete cards: #ST.744 at 4,000 and #2248 at 8,000
    monkeypatch.chdir(tmp_path)  # crops and CSVs land in the temp folder
    target = Target("Starveil AWP", "Sniper", "Limited", 5000, None, None, True)
    store = Store(tmp_path / "output")
    store.begin_cycle("c1")
    r = scan_visible(img, target, store, tmp_path / "output", NOW)

    assert (r["read"], r["matches"], r["records"], r["clipped"]) == (2, 1, 20, 1)
    assert len(r["lines"]) == 1 and r["lines"][0].startswith("[LIMITED] [Starveil AWP] [#ST.744] [4,000] [output/")
    crops = list((tmp_path / "output" / "screenshots" / "matches").glob("*.png"))
    assert len(crops) == 1
    with open(tmp_path / "output" / "listings.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(x["serial"], x["price"], x["matched"]) for x in rows] == [("744", "4000", "true"), ("2248", "8000", "false")]
