"""
Construction cost by area.
==========================

The model used one flat $/sqft for every lot. That was always a simplification, and
a developer Tal spoke to put a number on how wrong it can be: on the flat, easy-access
streets — the Alphabet area — you can build genuinely luxury for around $700/sqft.
Homes there sell in the ~$5M range, so the finish level steps down from ultra-luxury
without hurting the exit.

The cost driver is terrain and access more than anything else. A flat lot with a wide
street takes standard foundations, ordinary crane and delivery access, and no shoring.
A hillside or bluff lot adds caissons, retaining, difficult delivery, and often a
longer schedule — all of which land in the $/sqft number.

These are DEFAULTS, not findings. They shift the starting point per lot so the batch
isn't uniformly wrong; the per-lot override in the app still wins, and should be used
whenever there's a real bid.
"""
from __future__ import annotations
from typing import Optional

# Alphabet streets — the flat grid in the Palisades bluffs area. Named for the
# alphabetical street ordering; flat terrain, easy access, cheaper to build.
_ALPHABET = {
    "albright", "bashford", "bollinger", "carey", "chautauqua", "dalehurst",
    "earlham", "embury", "fiske", "frontera", "galloway", "goucher", "hartzell",
    "iliff", "jacon", "kagawa", "lachman", "marquette", "monument", "muskingum",
    "northfield", "ocampo", "oreo", "radcliffe", "swarthmore", "toyopa", "via",
}

# Streets that read as hillside / bluff / canyon — harder and costlier to build.
_HILLSIDE_HINTS = (
    "castellammare", "posetano", "revello", "tramonto", "breve", "corto",
    "vigilancia", "stassi", "sunset", "palisades dr", "highlands", "vereda",
    "chastain", "michael", "charmel", "lachman ln", "puerto", "cumbre",
)


def area_construction_cost(address: Optional[str], default: float = 1000.0,
                           lat: Optional[float] = None,
                           lon: Optional[float] = None) -> dict:
    """
    Suggest a $/sqft starting point from the address.

    Returns the suggestion plus a short reason, so the number never appears without
    the reasoning attached. Falls back to the default when the street isn't
    recognised — a wrong guess is worse than the flat assumption.
    """
    if not address:
        return dict(psf=default, band="unknown", why="No address — using the default.")
    a = str(address).lower()

    for hint in _HILLSIDE_HINTS:
        if hint in a:
            return dict(psf=1150.0, band="hillside",
                        why=("Reads as a hillside, bluff or canyon street. Caissons, "
                             "retaining, shoring and awkward delivery access push cost "
                             "well above the flats. Confirm with a site visit."))

    tokens = set(a.replace(",", " ").split())
    if tokens & _ALPHABET:
        return dict(psf=700.0, band="alphabet-flats",
                    why=("Alphabet-area street — flat terrain, easy access. A developer "
                         "quoted ~$700/sqft here for genuinely luxury work: homes trade "
                         "around $5M, so the finish level can step down from "
                         "ultra-luxury without hurting the exit."))

    return dict(psf=default, band="default",
                why=("Street not recognised as either flats or hillside — using the "
                     "sidebar default. Set it per lot once you know the terrain."))
