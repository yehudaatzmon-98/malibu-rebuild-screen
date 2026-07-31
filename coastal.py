"""
Coastal Commission exposure — Pacific Palisades.
================================================

WHY THIS EXISTS
The tool treated every City of LA lot as governed by EO1/EO8 alone. That is wrong
for a meaningful share of Palisades lots, because much of Pacific Palisades sits in
the Coastal Zone, and:

  * The City of LA does NOT have a fully certified Local Coastal Program for Pacific
    Palisades. That creates a dual-jurisdiction situation rather than the clean
    "local government issues the permit" arrangement that exists in, say, Malibu.

  * Some Palisades areas fall under the Commission's RETAINED ORIGINAL JURISDICTION,
    where the Commission itself issues the CDP rather than the City. A City approval
    is not sufficient there.

  * Other areas are in DUAL PERMIT JURISDICTION — the project needs a City CDP and a
    separate Commission CDP or exemption.

  * Even outside those, certain categories are APPEALABLE to the Commission:
    generally projects between the sea and the first public road, within 300 feet of
    the beach, or on tidelands. An appeal triggers de novo review against Coastal Act
    policies.

WHAT THE EMERGENCY ORDERS DO AND DON'T DO
Governor's EO N-4-25 (and successors) suspended CEQA and Coastal Act permitting for
reconstruction within 110% of the original structure. Mayor's EO8 extended local
streamlining to zoning-compliant non-like-for-like single-family rebuilds in the
Coastal Zone. So a like-for-like rebuild is largely insulated today.

The exposure appears when you exceed the envelope — which is precisely the fund's
upside case. A project pushing past 110% in the Coastal Zone can land back in CDP
territory, and in dual-permit areas that means the Commission too. There is also a
Categorical Exclusion (CATEX) route under Order E-79-8 for some geographies.

WHAT THIS MODULE CLAIMS, AND WHAT IT DOESN'T
It does NOT claim to determine jurisdiction. The Coastal Zone boundary is an
irregular legal line that runs from roughly 1,000 feet to several miles inland
depending on location, and the sub-jurisdictions inside it are irregular too. A
distance heuristic cannot resolve that, and pretending otherwise would be worse than
saying nothing.

What it DOES is triage: flag which lots are near enough to the coast that coastal
jurisdiction is plausible, so nobody assumes a clean EO8 path on a lot that may need
Commission involvement — and hand over the authoritative sources to check each one.
Treat the output as "check this" or "probably fine", never as a determination.
"""
from __future__ import annotations
import math
import urllib.parse
from typing import Optional

# The Palisades shoreline runs roughly WNW-ESE along PCH. These points trace it
# from Topanga down to Santa Monica; distance to this polyline approximates distance
# to the coast well enough for triage at the mile scale.
_SHORE = [
    (34.0392, -118.5860),  # Topanga Cyn / PCH
    (34.0365, -118.5650),
    (34.0340, -118.5480),
    (34.0320, -118.5330),  # Sunset / PCH
    (34.0295, -118.5180),
    (34.0260, -118.5050),
    (34.0230, -118.4950),  # Santa Monica Canyon
    (34.0180, -118.4870),
]


def _haversine_mi(lat1, lon1, lat2, lon2) -> float:
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def distance_to_shore_mi(lat: float, lon: float) -> Optional[float]:
    """Shortest distance from a point to the traced shoreline, in miles."""
    if lat is None or lon is None:
        return None
    try:
        return min(_haversine_mi(lat, lon, sy, sx) for sy, sx in _SHORE)
    except (TypeError, ValueError):
        return None


def _links(address: Optional[str]) -> str:
    enc = urllib.parse.quote_plus(str(address).strip()) if address else None
    zimas = "https://zimas.lacity.org/"
    ccc = "https://www.coastal.ca.gov/"
    out = (f"&bull; <b><a href='{zimas}' target='_blank'>ZIMAS</a></b> — the City's parcel "
           f"map. Search the address and read the <i>Coastal Zone</i> and <i>Coastal "
           f"Jurisdiction</i> fields. This is the free, authoritative first check.<br>"
           f"&bull; <b><a href='{ccc}' target='_blank'>Coastal Commission South Coast "
           f"District</a></b> — confirms dual-permit or retained-jurisdiction status, and "
           f"handles exemption applications.<br>"
           f"&bull; <b>CATEX (Categorical Exclusion Order E-79-8)</b> — a route for some "
           f"geographies exceeding 10%. Check the CATEX map for eligibility before "
           f"assuming a CDP is required.")
    if enc:
        out += (f"<br>&bull; <a href='https://www.google.com/search?q=ZIMAS+{enc}+coastal+zone' "
                f"target='_blank'>Search this address</a>")
    return out


def coastal_flag(jurisdiction: str, lat: Optional[float], lon: Optional[float],
                 address: Optional[str] = None, over_envelope: bool = False) -> Optional[dict]:
    """
    Triage a lot's Coastal Commission exposure.

    Returns None when it isn't relevant (Malibu is handled by its own certified LCP
    elsewhere in the tool; every Malibu lot is in the Coastal Zone by definition).

    tier: HIGH   — within ~0.25 mi of the shore. Likely appealable at minimum
                   (seaward of the first public road / within 300ft of the beach),
                   plausibly dual-permit or retained jurisdiction.
          LIKELY  — within ~1.5 mi. Much of Pacific Palisades at this range is inside
                   the Coastal Zone. Must be checked.
          POSSIBLE— within ~3 mi. The boundary runs several miles inland in places.
          UNLIKELY— beyond that.
    """
    if jurisdiction == "MALIBU":
        return None
    d = distance_to_shore_mi(lat, lon)
    if d is None:
        return dict(tier="UNKNOWN", dist_mi=None, note=(
            "<b>Coastal Zone status unknown — no coordinates for this lot.</b><br>"
            "Much of Pacific Palisades sits in the Coastal Zone, and the City of LA has "
            "no fully certified Local Coastal Program here, so some parcels need the "
            "Coastal Commission directly rather than just City approval. Check it:<br>"
            + _links(address)))

    if d <= 0.25:
        tier, headline = "HIGH", (
            f"<b style='color:#7a2518'>COASTAL COMMISSION EXPOSURE — HIGH.</b> About "
            f"{d:.2f} mi from the shoreline.")
        body = ("At this range a project is very likely appealable to the Commission at "
                "minimum — the appealable categories include development between the sea "
                "and the first public road, within 300 feet of the beach, and on "
                "tidelands. Some Palisades parcels are in <b>dual permit jurisdiction</b> "
                "(City CDP <i>and</i> a Commission CDP or exemption), and some fall under "
                "the Commission's <b>retained original jurisdiction</b>, where the "
                "Commission issues the permit and a City approval is not sufficient.")
    elif d <= 1.5:
        tier, headline = "LIKELY", (
            f"<b style='color:#8a5a00'>COASTAL ZONE — LIKELY.</b> About {d:.2f} mi from "
            f"the shoreline.")
        body = ("Much of Pacific Palisades at this distance is inside the Coastal Zone. "
                "The City has no fully certified LCP here, so confirm whether this parcel "
                "needs Commission involvement before underwriting a clean EO8 path.")
    elif d <= 3.0:
        tier, headline = "POSSIBLE", (
            f"<b>Coastal Zone — possible.</b> About {d:.2f} mi from the shoreline.")
        body = ("The Coastal Zone boundary runs from roughly 1,000 feet to several miles "
                "inland depending on location, so distance alone doesn't settle it. Worth "
                "a two-minute check.")
    else:
        tier, headline = "UNLIKELY", (
            f"<b>Coastal Zone — unlikely.</b> About {d:.1f} mi from the shoreline.")
        body = ("Probably outside the Coastal Zone, but the boundary is irregular. If the "
                "plan exceeds the rebuild envelope, confirm before relying on it.")

    envelope_note = ""
    if over_envelope:
        envelope_note = (
            "<br><br><b>And this matters here specifically:</b> the emergency orders "
            "insulate a like-for-like rebuild — the Governor's orders suspended Coastal "
            "Act permitting within 110% of the original structure, and EO8 extended local "
            "streamlining to zoning-compliant non-like-for-like single-family rebuilds. "
            "<b>The exposure appears when you push past the envelope</b>, which is exactly "
            "the upside case. Exceeding 110% can land the project back in CDP territory, "
            "and in dual-permit areas that means the Commission as well as the City. "
            "There is a Categorical Exclusion (CATEX) route under Order E-79-8 for some "
            "geographies — check the CATEX map before assuming a full CDP.")

    return dict(tier=tier, dist_mi=round(d, 2), note=(
        headline + "<br>" + body + envelope_note +
        "<br><br><b>Verify it — this is a triage flag, not a determination:</b><br>"
        + _links(address) +
        "<br><span class='cite'>The Coastal Zone boundary is an irregular legal line and "
        "the sub-jurisdictions inside it are irregular too. Distance from the shore "
        "identifies which lots need checking; it does not decide them. A written "
        "jurisdiction determination is worth requesting before any offer on a lot near "
        "the coast.</span>"))
