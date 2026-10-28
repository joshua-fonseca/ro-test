"""Does a listing satisfy a target? Pure function, no I/O."""
from models import Listing, Target


def matches(target: Target, listing: Listing) -> bool:
    if target.max_price is None or listing.price is None or listing.price > target.max_price:
        return False
    if target.max_serial is not None and (listing.serial is None or listing.serial > target.max_serial):
        return False
    if target.stattrak == "with" and listing.stattrak is not True:
        return False
    if target.stattrak == "without" and listing.stattrak is not False:
        return False
    return True
