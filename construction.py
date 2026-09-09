"""
Construction cost by area.
==========================

The model used one flat $/sqft for every lot. A developer Tal spoke to put a number
on how wrong that can be: on the flat, easy-access Alphabet streets you can build
genuinely luxury for around $700/sqft. Hillside and bluff lots run ~$1,150 for
caissons, retaining, shoring and awkward delivery.

WHAT WAS WRONG WITH THE FIRST VERSION (8 Sep 2026)

Street matching was done on bare tokens. `via` was in the flats set, so every Spanish
street name in the Palisades was priced as flat ground: Via Cresta, Via Anita and
Via La Costa are ridge and canyon streets and all three were quoted $700/sqft.
`jacon` was in the flats set too; Jacon Way sits in Marquez Knolls at 34.052/-118.547
on lots of 12,500 to 23,600 sqft. `sunset` was in the hillside set, which would have
caught flat stretches of Sunset the other way.

On a 138-lot Redfin export the effect was not marginal. Seven of the top ten ranked
lots were Via or Jacon streets carrying flats pricing. Correcting construction alone
moved every one of them from a negative margin over market to a positive one, which
is to say from a buy to a pass. $450/sqft across a 5,000 sqft rebuild is $2.25M.

WHAT CHANGED

1. Full street-name matching, not tokens. A street is matched on its name, so `via`
   no longer catches `Via De La Paz` (the flat village street) and `Via Cresta`
   (a ridge) in the same net.

2. Lot area as a secondary terrain signal, in ONE direction only. Palisades flats
   were platted at 4,000 to 8,500 sqft; the known-flats streets in the export median
   7,802 sqft with a 90th percentile of 10,698. Known hillside streets median 16,113.
   So a large lot is evidence of hillside. A small lot is NOT evidence of flats:
   Castellammare parcels run 3,846 and 6,287 sqft and are bluff. The rule fires one
   way and stays silent the other.

3. Unrecognised streets return `band="unknown"` with `confidence="none"` instead of
   silently taking the sidebar default. On this export 79 of 138 addresses matched
   neither list. Sixteen of those were priced as if the terrain were known. The
   caller should now flag them rather than rank them.

These remain DEFAULTS. The per-lot override wins, and should be used whenever there
is a real bid.
"""
from __future__ import annotations
import re
from typing import Optional

PSF_FLATS = 700.0
PSF_HILLSIDE = 1150.0

# Lot area above which a Palisades parcel is treated as hillside on area alone.
# Calibrated on the 8 Sep 2026 export: at 12,000 sqft this misflags 2 of 28
# known-flats lots. Raising it further starts missing real hillside.
LOT_HILLSIDE_SQFT = 12_000

# ---------------------------------------------------------------------------
# Flat, easy-access streets. The Alphabet grid plus the flat village streets.
# Matched on the full street name, so 'via de la paz' does not drag in 'via cresta'.
_FLATS = (
    "albright", "alma real", "bashford", "bestor", "bollinger", "carey",
    "dalehurst", "de pauw", "earlham", "el medio", "embury", "fiske", "frontera",
    "galloway", "goucher", "hartzell", "haverford", "iliff", "kagawa",
    "monument", "muskingum", "northfield", "ocampo", "oreo", "radcliffe",
    "swarthmore", "toyopa", "via de la paz", "friends", "hampden", "beirut",
    "mount holyoke", "las lomas ave",
)

# Hillside, bluff and canyon streets. Higher cost and usually longer schedule.
_HILLSIDE = (
    "castellammare", "posetano", "revello", "tramonto", "breve", "corto",
    "vigilancia", "stassi", "puerto del mar", "paseo miramar", "los liones",
    "palisades dr", "vereda", "chastain", "charmel", "lachman ln", "cumbre verde",
    "monte hermoso", "monte grande", "calle bellevista", "calle de sarah",
    "enchanted way", "enchanted pl", "pequeno", "jacon", "via anita", "via cresta",
    "via la costa", "via de las olas", "alta mura", "glenhaven", "las pulgas",
    "berea", "hightree", "lecco", "bellino", "chapala", "marinette", "tellem",
    "palmera", "bienveneda", "las casas", "erskine", "patterson", "livorno",
    "akron", "scenic", "las lomas pl",
)


def _street(address: str) -> str:
    """Lowercase the address and drop the leading house number."""
    a = str(address).lower().replace(",", " ")
    parts = a.split()
    if parts and any(ch.isdigit() for ch in parts[0]):
        parts = parts[1:]
    # drop a leading directional so 'n marquette' matches 'marquette'
    if parts and parts[0] in ("n", "s", "e", "w", "north", "south", "east", "west"):
        parts = parts[1:]
    return " ".join(parts)


def area_construction_cost(address: Optional[str], default: float = 1000.0,
                           lat: Optional[float] = None,
                           lon: Optional[float] = None,
                           lot_sqft: Optional[float] = None,
                           parcel_hillside: Optional[bool] = None,
                           bearing_depth_ft: Optional[float] = None,
                           foundation: Optional[str] = None) -> dict:
    """
    Suggest a $/sqft starting point from the address, with the reasoning attached.

    Returns psf, band, confidence and why. `confidence` is the field the caller
    should branch on:

        "street"  - the street is on a curated list. Use it.
        "lot"     - inferred from lot area alone. Directionally sound, confirm it.
        "none"    - no signal. The number returned is the sidebar default and
                    carries no information. FLAG THIS LOT, do not rank on it.
    """
    # ---------------------------------------------------------------- 8 Sep 2026
    # HILLSIDE DESIGNATION IS NOT HILLSIDE COST. 623 N Marquette carries Hillside
    # Ordinance YES, Hillside Grading Area YES and Baseline Hillside Ordinance Yes on
    # its parcel record, and its 2004 Schick geotechnical report finds dense alluvial
    # terrace at 1 to 6 feet below grade, conventional spread footings, and no hard
    # excavation. That is ordinary construction on a parcel the code calls hillside.
    # 1228 Las Lomas carries the same designations and finds 7.5 feet of uncertified
    # fill over bedrock at 11 feet in a landslide hazard zone. Same flag, opposite cost.
    #
    # So the parcel hillside flag governs the ENVELOPE (Baseline Hillside Ordinance
    # sets residential floor area) and the GEOTECHNICAL findings govern the COST.
    # Where a soils report exists, it outranks every heuristic below.
    if bearing_depth_ft is not None or foundation:
        shallow = (bearing_depth_ft is not None and bearing_depth_ft <= 6)
        conventional = bool(foundation and
                            re.search(r"spread|pad|conventional|continuous", foundation, re.I))
        # NOT a bare "deep": LADBS reports say "deepened pad footings" for the
        # ordinary shallow case, which this used to misread as deep foundations.
        deep = bool(foundation and re.search(
            r"caisson|\bpiles?\b|shoring|drilled pier|grade beam", foundation, re.I))
        if deep or (bearing_depth_ft is not None and bearing_depth_ft > 10):
            return dict(psf=PSF_HILLSIDE, band="hillside", confidence="geotechnical",
                        why=("Soils report indicates deep foundations or bearing well "
                             "below grade. This is the expensive case and the figure is "
                             "sourced rather than inferred. Confirm against a real bid."))
        if shallow and conventional:
            return dict(psf=default, band="designated-hillside-benign-soil",
                        confidence="geotechnical",
                        why=("Soils report finds competent bearing material near grade and "
                             "conventional spread or pad footings. The parcel may still be "
                             "flagged Hillside for zoning, which governs floor area, but "
                             "the FOUNDATION is ordinary. Neither the $700 flats figure nor "
                             "the $1,150 hillside figure is right here. Price this lot from "
                             "a bid, not a band."))

    if not address:
        return dict(psf=default, band="unknown", confidence="none",
                    why="No address. Using the sidebar default, which is not a finding.")

    s = _street(address)

    # ---------------------------------------------------------------- 8 Sep 2026
    # THE PARCEL RECORD OUTRANKS THE STREET NAME. `parcel_hillside` was accepted by
    # this function and never read, so a street-name match decided the cost band on
    # its own. That is wrong on every mixed street, and most of the long streets here
    # are mixed: Livorno runs flat through Lower Marquez Knolls and then climbs the
    # ridge, and 16860 Livorno is Hillside Area NO on ZIMAS, is described as a flat
    # lot, and photographs as a flat pad. It was being priced at $1,150 hillside on
    # the substring "livorno" alone, which killed a lot that should have been costed
    # at the flats band. "sunset" would have done the same to flat Sunset Blvd
    # addresses had it been on the list.
    #
    # Where ZIMAS and the street list disagree, ZIMAS wins and the answer is demoted
    # to the flats band with the conflict stated, NOT silently resolved. Note the
    # limit of this: Hillside Area NO is a zoning designation, not a soils finding.
    # Every Palisades parcel checked so far also carries Special Grading Area YES.
    # So this returns the flats band as the defensible starting point and says
    # plainly that only a geotechnical report settles it.
    if parcel_hillside is not None:
        street_says_hillside = any(name in s for name in _HILLSIDE)
        street_says_flat = any(name in s for name in _FLATS)
        if parcel_hillside is False and street_says_hillside:
            return dict(psf=PSF_FLATS, band="flats-by-parcel-record", confidence="parcel",
                        why=("CONFLICT, resolved to the parcel record. The street is on the "
                             "hillside list but ZIMAS returns Hillside Area NO for this "
                             "parcel. These streets are mixed: they run flat at one end and "
                             "climb at the other, so the street name is not evidence about "
                             "this lot. Costed at the flats band. This is a zoning "
                             "designation, not a soils finding, and only a geotechnical "
                             "report settles the foundation."))
        if parcel_hillside is True and street_says_flat:
            return dict(psf=PSF_HILLSIDE, band="hillside-by-parcel-record", confidence="parcel",
                        why=("CONFLICT, resolved to the parcel record. The street is on the "
                             "flats list but ZIMAS returns Hillside Area YES for this parcel, "
                             "which also governs the buildable envelope under the Baseline "
                             "Hillside Ordinance. Costed at the hillside band. Confirm with "
                             "geotechnical before this figure carries weight."))

    for name in _HILLSIDE:
        if name in s:
            return dict(psf=PSF_HILLSIDE, band="hillside", confidence="street",
                        why=("Hillside, bluff or canyon street. Caissons, retaining, "
                             "shoring and awkward delivery access push cost well above "
                             "the flats, and the schedule with it. Confirm on a site visit."))

    for name in _FLATS:
        if name in s:
            return dict(psf=PSF_FLATS, band="alphabet-flats", confidence="street",
                        why=("Flat, easy-access street. A developer quoted ~$700/sqft "
                             "here for genuinely luxury work: homes trade around $5M, so "
                             "the finish level can step down from ultra-luxury without "
                             "hurting the exit."))

    # Area signal, one direction only. A big lot in 90272 is subdivided hillside.
    # A small lot proves nothing: Castellammare bluff parcels run under 6,500 sqft.
    if lot_sqft and lot_sqft >= LOT_HILLSIDE_SQFT:
        return dict(psf=PSF_HILLSIDE, band="hillside", confidence="lot",
                    why=(f"Street not on either list, but the lot is {lot_sqft:,.0f} sqft. "
                         f"Palisades flats were platted at 4,000 to 8,500 sqft; parcels "
                         f"this size are subdivided hillside. Treated as hillside on area "
                         f"alone. Confirm the terrain before this figure carries weight."))

    return dict(psf=default, band="unknown", confidence="none",
                why=("Street not recognised and the lot is not large enough to infer "
                     "terrain. The figure shown is the sidebar default and is NOT a "
                     "finding about this lot. Set it per lot, or treat the ranking as "
                     "unresolved here."))
