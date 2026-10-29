"""Does a listing satisfy a target? Pure function, no I/O."""
from models import Listing, Target
from parsing import price_high


def matches(target: Target, listing: Listing) -> bool:
    if target.max_price is None or listing.price is None:
        return False
    # '11.7k' can be 11,799: it only matches if the highest price it can mean is within the limit
    if price_high(listing.price, listing.price_approx) > target.max_price:
        return False
    if target.max_serial is not None and (listing.serial is None or listing.serial > target.max_serial):
        return False
    return True
