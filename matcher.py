"""Does a listing satisfy a target? Pure function, no I/O."""
from models import Listing, Target


def matches(target: Target, listing: Listing) -> bool:
    if target.max_price is None or listing.price is None or listing.price > target.max_price:
        return False
    if target.max_serial is not None and (listing.serial is None or listing.serial > target.max_serial):
        return False
    return True
