import csv
import json
import logging
from datetime import datetime, timezone

import pytest

from scanner.logic.models import Listing, Target
from scanner.logic.storage import Store, add_discovered_skins, append_csv, format_match_line, listing_id, setup_run_log

NOW = datetime(2026, 10, 28, 13, 5, tzinfo=timezone.utc)
TARGET = Target("Nocturne Marlin [Rainbow]", "Sniper", "Secret", 9000, None, True)


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def crop():
    return "output/screenshots/matches/x.png", "ok"


def test_listing_id_ignores_price_but_not_serial_or_seller():
    a = listing_id(TARGET, Listing(8700, 610, False, "Bob123"))
    assert a == listing_id(TARGET, Listing(8000, 610, False, "Bob123", price_approx=True))
    assert a == listing_id(TARGET, Listing(8700, 610, False, "bob123"))
    assert a != listing_id(TARGET, Listing(8700, 611, False, "Bob123"))
    assert a != listing_id(TARGET, Listing(8700, 610, True, "Bob123"))
    assert a != listing_id(TARGET, Listing(8700, 610, False, "Ann"))
    # no serial and no seller: the price tells listings apart
    assert listing_id(TARGET, Listing(8700, None, False)) != listing_id(TARGET, Listing(7500, None, False))


def test_append_csv_writes_header_once(tmp_path):
    p = tmp_path / "sub" / "a.csv"
    append_csv(p, ["a", "b"], {"a": 1, "b": 2})
    append_csv(p, ["a", "b"], {"a": 3, "b": 4})
    assert rows(p) == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def test_match_line_format():
    line = format_match_line(TARGET, Listing(8700, 291, True, "Bob"), "output/s.png")
    assert line == "[SECRET] [Nocturne Marlin [Rainbow]] [#ST.291] [8,700] [output/s.png]"
    assert "[Unknown]" in format_match_line(TARGET, Listing(8700, None, None), "p")
    assert "[ST.4-digit]" in format_match_line(TARGET, Listing(8700, None, True, serial_digits=4), "p")
    assert "[3-digit]" in format_match_line(TARGET, Listing(8700, None, False, serial_digits=3), "p")
    assert "[PRICE_UNREADABLE]" in format_match_line(TARGET, Listing(None, 1, False), "p")


def test_new_match_notifies_once_and_writes_both_csvs(tmp_path):
    s = Store(tmp_path)
    s.begin_cycle("c1")
    line = s.record(NOW, TARGET, Listing(8700, 610, False, "Bob123"), True, crop)
    assert line == "[SECRET] [Nocturne Marlin [Rainbow]] [#610] [8,700] [output/screenshots/matches/x.png]"
    assert s.record(NOW, TARGET, Listing(8700, 610, False, "Bob123"), True, crop) is None  # scroll overlap
    assert len(rows(tmp_path / "listings.csv")) == 1 and len(rows(tmp_path / "matches.csv")) == 1
    m = rows(tmp_path / "matches.csv")[0]
    assert m["screenshot_path"] and m["crop_status"] == "ok" and m["observed_at"].endswith("+00:00")


def test_non_match_is_logged_but_not_a_match(tmp_path):
    s = Store(tmp_path)
    s.begin_cycle("c1")
    assert s.record(NOW, TARGET, Listing(99999, 1, False, "A"), False, crop) is None
    assert rows(tmp_path / "listings.csv")[0]["matched"] == "false"
    assert not (tmp_path / "matches.csv").exists()


def test_later_cycles_append_listings_but_do_not_renotify(tmp_path):
    s = Store(tmp_path)
    listing = Listing(8700, 610, False, "Bob123")
    s.begin_cycle("c1"); assert s.record(NOW, TARGET, listing, True, crop); s.end_cycle()
    s.begin_cycle("c2"); assert s.record(NOW, TARGET, listing, True, crop) is None; s.end_cycle()
    assert len(rows(tmp_path / "listings.csv")) == 2 and len(rows(tmp_path / "matches.csv")) == 1


def test_price_change_while_matching_is_recorded_without_renotifying(tmp_path):
    s = Store(tmp_path)
    s.begin_cycle("c1"); s.record(NOW, TARGET, Listing(8700, 610, False, "Bob"), True, crop); s.end_cycle()
    s.begin_cycle("c2"); line = s.record(NOW, TARGET, Listing(8000, 610, False, "Bob"), True, crop)
    assert line is None
    assert [r["price"] for r in rows(tmp_path / "listings.csv")] == ["8700", "8000"]
    assert list(s.state.values())[0]["price"] == 8000


def test_requalifying_after_failing_notifies_again(tmp_path):
    s = Store(tmp_path)
    for scan, price, ok in [("c1", 8700, True), ("c2", 99999, False), ("c3", 8000, True)]:
        s.begin_cycle(scan)
        line = s.record(NOW, TARGET, Listing(price, 610, False, "Bob"), ok, crop)
        s.end_cycle()
        assert (line is not None) == (scan != "c2")
    assert len(rows(tmp_path / "matches.csv")) == 2


def test_state_survives_restart_without_renotifying(tmp_path):
    s = Store(tmp_path)
    s.begin_cycle("c1"); s.record(NOW, TARGET, Listing(8700, 610, False, "Bob"), True, crop)
    s2 = Store(tmp_path)  # simulated restart
    s2.begin_cycle("c2")
    assert s2.record(NOW, TARGET, Listing(8700, 610, False, "Bob"), True, crop) is None
    assert not list(tmp_path.glob("*.tmp"))


def test_absent_listing_is_marked_not_observed_not_removed(tmp_path):
    s = Store(tmp_path)
    s.begin_cycle("c1"); s.record(NOW, TARGET, Listing(8700, 610, False, "Bob"), True, crop); s.end_cycle()
    s.begin_cycle("c2"); s.end_cycle()
    entry = json.loads((tmp_path / "listing_state.json").read_text()).popitem()[1]
    assert entry["observed_in_latest_cycle"] is False and entry["last_seen_scan"] == "c1"


def test_naive_timestamp_is_rejected(tmp_path):
    s = Store(tmp_path)
    s.begin_cycle("c1")
    with pytest.raises(AssertionError):
        s.record(datetime(2026, 1, 1), TARGET, Listing(1, 1, False, "A"), True, crop)


def test_scan_log_appends_and_is_never_cleared(tmp_path):
    for _ in range(2):
        s = Store(tmp_path)
        s.begin_cycle("c1")
        s.log_scan(NOW, TARGET, "complete", listings_seen=6, matches=1)
    assert len(rows(tmp_path / "scan_log.csv")) == 2


def test_discovery_appends_dedups_and_fills_only_skin_name(tmp_path):
    p = tmp_path / "discovered_skins.csv"
    assert add_discovered_skins(p, ["A", "B", "a", " B "]) == ["A", "B"]
    assert add_discovered_skins(p, ["b", "C"]) == ["C"]
    got = rows(p)
    assert [r["skin_name"] for r in got] == ["A", "B", "C"]
    assert all(v == "" for r in got for k, v in r.items() if k != "skin_name")


def test_discovery_dry_run_writes_nothing(tmp_path):
    p = tmp_path / "discovered_skins.csv"
    assert add_discovered_skins(p, ["A"], dry_run=True) == ["A"]
    assert not p.exists()


def test_discovery_never_touches_targets_csv(tmp_path):
    t = tmp_path / "targets.csv"
    t.write_text("skin_name,category,rarity,max_price,max_serial,enabled\nA,Sniper,Secret,1,,true\n")
    before = t.read_bytes()
    add_discovered_skins(tmp_path / "discovered_skins.csv", ["A", "B"])
    assert t.read_bytes() == before


def test_run_log_truncates_but_csv_history_stays(tmp_path):
    append_csv(tmp_path / "scan_log.csv", ["a"], {"a": 1})
    (tmp_path / "run.log").write_text("old run")
    h = setup_run_log(tmp_path)
    try:
        logging.getLogger("t").info("new run")
        h.flush()
        text = (tmp_path / "run.log").read_text()
        assert "old run" not in text and "new run" in text
        assert len(rows(tmp_path / "scan_log.csv")) == 1
    finally:
        logging.getLogger().removeHandler(h); h.close()


def test_locked_csv_keeps_rows_and_writes_them_when_unlocked(tmp_path):
    p = tmp_path / "matches.csv"
    append_csv(p, ["a"], {"a": 1})
    p.chmod(0o444)  # stands in for Excel holding the file open
    try:
        append_csv(p, ["a"], {"a": 2})  # must not raise
        append_csv(p, ["a"], {"a": 3})
        assert [r["a"] for r in rows(p)] == ["1"]
    finally:
        p.chmod(0o644)
    append_csv(p, ["a"], {"a": 4})
    assert [r["a"] for r in rows(p)] == ["1", "2", "3", "4"]


def test_unreadable_price_does_not_reset_match_state(tmp_path):
    s = Store(tmp_path)
    notified = []
    for scan, price in [("c1", 8700), ("c2", None), ("c3", 8700)]:
        s.begin_cycle(scan)
        ok = price is not None and price <= 9000
        notified.append(s.record(NOW, TARGET, Listing(price, 610, False, "Bob"), ok, crop) is not None)
        s.end_cycle()
    assert notified == [True, False, False]
    assert len(rows(tmp_path / "matches.csv")) == 1


def test_clear_matches_removes_matches_and_pictures_and_lets_a_card_match_again(tmp_path):
    from scanner.logic.storage import clear_matches
    store = Store(tmp_path)
    store.begin_cycle("c1")
    listing = Listing(8700, 610, False)
    crop = lambda: ("shot.png", "ok")  # noqa: E731
    assert store.record(NOW, TARGET, listing, True, crop)
    (tmp_path / "screenshots" / "matches").mkdir(parents=True)
    (tmp_path / "screenshots" / "matches" / "a.png").write_bytes(b"x")
    assert clear_matches(tmp_path) == 1
    assert not (tmp_path / "matches.csv").exists() and not list((tmp_path / "screenshots" / "matches").glob("*.png"))
    assert (tmp_path / "listings.csv").exists()  # the history stays
    again = Store(tmp_path)  # a new run: the same card still qualifies and is reported again
    again.begin_cycle("c2")
    assert again.record(NOW, TARGET, listing, True, crop)
    assert clear_matches(tmp_path / "nothing-here") == 0  # a missing folder is fine
