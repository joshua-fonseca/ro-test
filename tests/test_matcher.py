from matcher import matches
from models import Listing, Target


def target(**kw):
    base = dict(skin_name="Nocturne Marlin [Rainbow]", category="Sniper", rarity="Secret",
                max_price=9000, max_serial=None, enabled=True)
    return Target(**{**base, **kw})


def test_price_boundary_is_inclusive():
    assert matches(target(), Listing(9000, 1, False))
    assert not matches(target(), Listing(9001, 1, False))


def test_unconfigured_price_never_matches():
    assert not matches(target(max_price=None), Listing(1, 1, False))


def test_unreadable_price_never_matches():
    assert not matches(target(), Listing(None, 1, False))


def test_serial_bound_inclusive_and_unknown_serial_fails():
    t = target(max_serial=500)
    assert matches(t, Listing(100, 500, False))
    assert not matches(t, Listing(100, 501, False))
    assert not matches(t, Listing(100, None, False))


def test_blank_serial_bound_accepts_any_including_unknown():
    assert matches(target(), Listing(100, None, False))
    assert matches(target(), Listing(100, 99999, False))


def test_serial_zero_is_a_real_serial_not_unknown():
    assert matches(target(max_serial=5), Listing(100, 0, False))


def test_approximate_price_is_compared_at_face_value():
    assert matches(target(max_price=12200), Listing(12200, 1, False, price_approx=True))
    assert not matches(target(max_price=12000), Listing(12200, 1, False, price_approx=True))
