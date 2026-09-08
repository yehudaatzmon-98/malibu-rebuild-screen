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
    "galloway", "goucher", "hartzell", "haverford", "iliff", "kagawa", "marquette",
    "monument", "muskingum", "northfield", "ocampo", "oreo", "radcliffe",
    "swarthmore", "toyopa", "via de la paz", "friends", "hampden", "beirut",
    "mount holyoke", "las lomas",
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
    "akron", "scenic",
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
                           lot_sqft: Optional[float] = None) -> dict:
    """
    Suggest a $/sqft starting point from the address, with the reasoning attached.

    Returns psf, band, confidence and why. `confidence` is the field the caller
    should branch on:

        "street"  - the street is on a curated list. Use it.
        "lot"     - inferred from lot area alone. Directionally sound, confirm it.
        "none"    - no signal. The number returned is the sidebar default and
                    carries no information. FLAG THIS LOT, do not rank on it.
    """
    if not address:
        return dict(psf=default, band="unknown", confidence="none",
                    why="No address. Using the sidebar default, which is not a finding.")

    s = _street(address)

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
