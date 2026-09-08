"""
intake.py — the free screen, run on listing text before anything is spent.
===========================================================
PCR / Palisades.  Added 10 September 2026.

WHY THIS MODULE EXISTS

Three lots sat in the pipeline for months and all three died on facts printed in
their own MLS remarks.

  1552 / 1555 Reseda Blvd — directions instruct the buyer to park and walk in on
  Sullivan Fire Road "since land is on a paper street". A paper street is a right
  of way that exists on the subdivision map and was never built. No dedicated
  improved frontage, no building permit. Listed since Nov 2024, still unsold at
  about $14/sf in the most expensive tier in the Palisades.

  1785 Alta Mura Rd — "these lots DO NOT need to be cleaned up as they were never
  built on". No prior structure means no EO1 and no EO8. Both are rebuild
  pathways attached to a structure destroyed in the fire. A parcel that never
  held a house is an ordinary ground-up entitlement under full LAMC with full
  CEQA and Coastal review, which is precisely the process the thesis exists to
  avoid. Cut from $2,495,000 to $999,000 over thirteen months, 434 days on
  market, in the tier that did not reprice after the fire.

Neither needed a ZIMAS pull or a records request. Both needed someone to read
the remarks. This module does that first, so the expensive steps only ever run
on lots that survive the free ones.

WHAT IT DOES NOT DO

It reads seller-authored marketing copy, which is unreliable in one direction:
sellers disclose defects tersely and omit them often. So a hit is close to
decisive and a miss means nothing. Every function here returns True (problem
found), False (positively contradicted), or None (silent, unscreened) and the
gate treats None as UNSCREENED rather than as a pass. Absence of a flag is not
a clear flag — the same rule the ZIMAS gates already use.
"""

from typing import Optional, Tuple

INTAKE_VERSION = "i1.0 · 10 Sep 2026"

# ------------------------------------------------------------- gate 0: access
# A lot with no legal improved frontage cannot be permitted, and creating access
# means dedicating and improving the street or negotiating a private easement
# across neighbours, plus LAFD sign-off on width, grade and turnaround for a
# hillside site. That is not a discount, it is a different business.
# HARD: language that only appears when the defect is real. A hit fails the lot.
_NO_ACCESS = (
    "PAPER STREET", "PAPER ROAD", "UNIMPROVED STREET", "NOT A DEDICATED",
    "UNDEDICATED", "NO LEGAL ACCESS", "NO ACCESS TO", "NO DIRECT ACCESS",
    "LANDLOCKED", "LAND LOCKED", "ACCESS EASEMENT NEEDED",
)
# SOFT: consistent with a defect but also with ordinary copy. These raise a flag
# for a human to check; they never fail a lot on their own. "Park your car and
# walk in on the fire road with a plat map" is three soft hits at once, which is
# what Reseda reads like even where the words "paper street" are edited out of a
# later version of the remarks.
_ACCESS_SOFT = (
    "FIRE ROAD", "FIRE RD", "ACCESS INFORMATION", "PLAT MAP",
    "PARK YOUR CAR", "WALK IN", "ON FOOT", "HIKE IN",
)
# phrases that positively establish frontage, checked first
_HAS_ACCESS = (
    "STREET TO STREET", "STREET-TO-STREET", "CUL-DE-SAC", "CUL DE SAC",
    "PAVED ROAD", "CITY STREET", "IMPROVED STREET", "FRONTS ON",
    "GATED DRIVEWAY", "DRIVEWAY", "CIRCULAR DRIVE",
)

# ------------------------------------------- gate 0b: the rebuild right exists
# EO1 and EO8 attach to a structure destroyed in the fire. Vacant land that never
# held a house carries no rebuild right, no prior square footage to verify under
# rule 1, and no EO8 bypass of local Coastal Act and CEQA review.
_NEVER_BUILT = (
    "NEVER BUILT", "NEVER BEEN BUILT", "NEVER DEVELOPED", "UNDEVELOPED LAND",
    "VACANT SINCE", "RAW LAND", "UNIMPROVED LOT", "UNIMPROVED LAND",
    "NO STRUCTURE HAS", "NEVER HAD A HOME", "NEVER HAD A HOUSE",
)
_WAS_BUILT = (
    "BURNED", "BURNT", "DESTROYED", "REBUILD", "RE-BUILD", "FIRE DAMAGE",
    "LOST IN THE FIRE", "PRIOR HOME", "PRIOR HOUSE", "PRIOR RESIDENCE",
    "THE HOME THAT SAT", "HOME THAT STOOD", "THAT SAT HERE", "STOOD HERE",
    "CERTIFICATE OF OCCUPANCY", "C OF O", "SCRAPE", "TEAR DOWN", "TEARDOWN",
    "YEAR BUILT", "BUILT IN 1", "BUILT IN 2",
)

# ------------------------------------------------- other free tells, not gates
_MULTI_PARCEL = ("TWO ADJACENT PARCELS", "TWO PARCELS", "ADJACENT PARCELS",
                 "THREE PARCELS", "BOTH PARCELS", "TWO LOTS", "TWO APN")
_SELLER_CARRY = ("SELLER MAY CARRY", "OWNER MAY CARRY", "SELLER FINANCING",
                 "OWNER WILL CARRY", "SELLER IS OPEN TO FINANCING",
                 "SELLER CARRY")


def _scan(blob: str, bad: Tuple[str, ...], good: Tuple[str, ...]) -> Tuple[Optional[bool], Optional[str]]:
    """Return (problem_found, matched phrase). None means the text is silent."""
    if not blob:
        return None, None
    t = blob.upper()
    for k in bad:
        if k in t:
            return True, k
    for k in good:
        if k in t:
            return False, k
    return None, None


def access_problem(blob: str) -> Tuple[Optional[bool], Optional[str]]:
    """True if the remarks describe a lot without legal improved frontage."""
    return _scan(blob, _NO_ACCESS, _HAS_ACCESS)


def never_built(blob: str, prior_sqft=None, year_built=None) -> Tuple[Optional[bool], Optional[str]]:
    """
    True if the parcel appears never to have held a structure.

    A prior square footage or a year built from the county record settles it and
    outranks the marketing copy, because a record beats a seller's adjective.
    """
    if prior_sqft:
        return False, "county prior sqft on file"
    if year_built:
        return False, f"county year built {year_built}"
    return _scan(blob, _NEVER_BUILT, _WAS_BUILT)


def screen(blob: str, prior_sqft=None, year_built=None) -> dict:
    """
    The whole free screen in one call. Run before ZIMAS, before records, before
    a phone call.
    """
    acc, acc_why = access_problem(blob)
    soft = [k for k in _ACCESS_SOFT if k in (blob or "").upper()]
    nb, nb_why = never_built(blob, prior_sqft, year_built)
    t = (blob or "").upper()

    fails = []
    if acc is True:
        fails.append(f"no legal street access ({acc_why.lower()})")
    if nb is True:
        fails.append(f"never built on, so no EO1/EO8 rebuild right ({nb_why.lower()})")

    return dict(
        fails=fails,
        access=acc, access_why=acc_why, access_soft=soft,
        never_built=nb, never_built_why=nb_why,
        unscreened=(acc is None or nb is None),
        multi_parcel=any(k in t for k in _MULTI_PARCEL),
        seller_carry=any(k in t for k in _SELLER_CARRY),
    )
