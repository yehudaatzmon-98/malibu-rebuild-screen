"""
Jurisdiction routing — which rulebook governs a parcel.
=======================================================

The fire crossed a city line. The rules did not.

Malibu and Pacific Palisades burned in the same fire on the same day and are
governed by structurally different rebuild regimes. Applying one to the other is
not a marginal error; it inverts the answer.

  MALIBU (incorporated city, own LCP)
    LCP & Zoning Code Interpretation No. 24, adopted 15 Oct 2025.
    Caps BULK (volume) *and* SQUARE FOOTAGE *and* HEIGHT, each at 110% of the
    prior structure. Three simultaneous ceilings [Issue No. 1].
    -> Raising ceilings costs habitable area. Volume binds. This is the finding
       that survived every correction: on 1923-1963 stock at 8-8.5ft prior
       ceilings, a 10ft luxury build yields LESS area than burned.

  CITY OF LOS ANGELES (Pacific Palisades is a NEIGHBOURHOOD of the City of LA,
  not a city — it has no separate permitting authority)
    Mayoral Emergency Executive Order 1 (revised 18 Mar 2025), and EO8
    (23 Jul 2025).
    EO1 caps FOOTPRINT and HEIGHT, each at 110%. It does NOT cap volume and does
    NOT cap gross square footage.
    -> Raising ceilings costs nothing on area. A new story is expressly permitted
       within the footprint and height caps. Gross sqft is an OUTPUT of
       footprint x stories, not a constraint.
    EO8 goes further: zoning-compliant NON-like-for-like single-family projects
    bypass local Coastal Act and CEQA review entirely. Under EO8 the prior
    envelope is not a ceiling at all — LAMC zoning is.

THE CONSEQUENCE FOR THE THESIS
  "The value of a burn lot comes from what burned on it" is a MALIBU-SPECIFIC
  truth. It follows from Interp. No. 24 capping gross square footage. In the
  Palisades under EO1/EO8 what burned barely constrains the rebuild; the lot and
  its zoning do. Two adjacent fire zones, opposite underwriting logic.

WHY THE LA BRANCH RETURNS *REVIEW* AND NOT A NUMBER
  EO1's cap is on FOOTPRINT. The Assessor publishes SQFTmain — GROSS square
  footage — not footprint, and not story count. A 4,527 sf two-storey home has a
  ~2,264 sf footprint; a single-storey one has 4,527. Those produce completely
  different EO1 envelopes and the parcel record cannot tell them apart.
  We have the rule. We do not have the input. So we name the rule, name the
  missing input, name where to get it, and refuse to invent the number.

  Per the EO1 guidelines, prior footprint is established by: issued building
  permits, Certificate of Occupancy, County Assessor records, or Coastal
  Commission documents; LADBS as-built plans exist for anything built after 1977.

UNKNOWN JURISDICTIONS FAIL LOUD
  A parcel whose SitusCity we don't recognise returns UNSCOREABLE. It never
  silently inherits a rulebook. That failure mode — a confident envelope computed
  under the wrong city's rule — is the one this module exists to prevent.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

MALIBU = "MALIBU"
CITY_OF_LA = "CITY_OF_LA"
UNKNOWN = "UNKNOWN"

# SitusCity values as the Assessor stores them.
# Pacific Palisades is a neighbourhood of the City of LA. The roll may carry it
# either as its own situs city or folded into LOS ANGELES — both route to the
# same rulebook, which is why we match on a set rather than a single string.
_MALIBU_SITUS = {"MALIBU"}
_LA_SITUS = {
    "LOS ANGELES",
    "PACIFIC PALISADES",
    "PACIFIC PALISADES AREA",
}


@dataclass
class Jurisdiction:
    code: str                 # MALIBU | CITY_OF_LA | UNKNOWN
    name: str                 # human label
    rulebook: str             # citation
    caps_gross_sqft: bool     # does the regime cap gross square footage?
    volume_binds: bool        # can raising ceilings cost habitable area?
    note: str = ""


def route(situs_city: Optional[str]) -> Jurisdiction:
    """Map an Assessor SitusCity to the governing rebuild regime."""
    if not situs_city:
        return Jurisdiction(
            UNKNOWN, "Unknown", "",
            caps_gross_sqft=False, volume_binds=False,
            note="County record carries no SitusCity. Jurisdiction undetermined, "
                 "so no rulebook applies. Not screened.")

    s = str(situs_city).upper().strip()

    if s in _MALIBU_SITUS or s.startswith("MALIBU"):
        return Jurisdiction(
            MALIBU, "City of Malibu",
            "LCP & Zoning Code Interpretation No. 24 / Zoning Code No. 15, adopted 15 Oct 2025",
            caps_gross_sqft=True, volume_binds=True,
            note="Caps bulk (volume), square footage, AND height, each at 110% of the "
                 "prior structure — three simultaneous ceilings [Issue No. 1]. Raising "
                 "ceilings costs habitable area.")

    if s in _LA_SITUS:
        return Jurisdiction(
            CITY_OF_LA, "City of Los Angeles",
            "Mayoral Emergency Executive Order 1 (rev. 18 Mar 2025); EO8 (23 Jul 2025)",
            caps_gross_sqft=False, volume_binds=False,
            note="EO1 caps FOOTPRINT and HEIGHT at 110%. It does not cap volume or "
                 "gross square footage. A new story is permitted within those caps, so "
                 "gross sqft is an output, not a ceiling. EO8 additionally lets "
                 "zoning-compliant non-like-for-like single-family projects bypass local "
                 "Coastal Act and CEQA review — under EO8 the prior envelope is not a "
                 "constraint at all; LAMC zoning is.")

    return Jurisdiction(
        UNKNOWN, f"{s.title()} (not modelled)", "",
        caps_gross_sqft=False, volume_binds=False,
        note=f"SitusCity '{s}' is outside the two regimes this tool models (City of "
             f"Malibu, City of Los Angeles). No rulebook applied. A parcel is never "
             f"screened under a jurisdiction's rule it isn't subject to.")


def la_review_note(prior_sqft: Optional[int], year_built: Optional[int]) -> str:
    """
    What the LA branch says instead of an envelope, and why.

    This is deliberately not a number. EO1 constrains footprint; the Assessor
    publishes gross sqft. The missing input is named, along with where to get it.
    """
    lines = [
        "<b>City of Los Angeles — EO1 / EO8 govern. Malibu's Interpretation No. 24 "
        "has no force here.</b>",
        "",
        "<b>The rule is materially more permissive than Malibu's:</b>",
        "&nbsp;&nbsp;&bull; EO1 caps <b>footprint</b> and <b>height</b> at 110% — not volume, "
        "not gross square footage.",
        "&nbsp;&nbsp;· Raising ceilings costs you nothing on area. The volume ceiling "
        "that binds every Malibu lot does not exist here.",
        "&nbsp;&nbsp;· A <b>new story</b> is expressly permitted provided it sits within "
        "the footprint and height caps. Gross sqft is an output of footprint × stories.",
        "&nbsp;&nbsp;· An attached garage up to 400 sf does not count toward footprint. "
        "A new attached ADU does not count against the 110% footprint.",
        "&nbsp;&nbsp;· <b>EO8</b>: a zoning-compliant non-like-for-like single-family "
        "rebuild bypasses local Coastal Act and CEQA review. Under EO8 the prior "
        "envelope is not a ceiling — LAMC zoning is.",
        "",
        "<b>Why this lot is not scored:</b>",
        "EO1's cap is on <b>prior footprint</b>. The Assessor publishes gross square "
        "footage and does not publish footprint or story count.",
    ]
    if prior_sqft:
        lines.append(
            f"County shows <b>{prior_sqft:,} sf gross</b>. If that was single-storey the "
            f"footprint is {prior_sqft:,}; if two-storey it is ~{round(prior_sqft/2):,}. "
            f"Those produce completely different EO1 envelopes and the parcel record "
            f"cannot distinguish them. Any envelope printed here would be a guess.")
    lines += [
        "",
        "<b>To unlock it — two inputs:</b> prior footprint and story count.",
        "Per the EO1 guidelines these are established by issued building permits, the "
        "Certificate of Occupancy, County Assessor records, or Coastal Commission "
        "documents.",
    ]
    if year_built and year_built >= 1977:
        lines.append(
            f"Built {year_built} — <b>LADBS holds as-built plans for anything after "
            f"1977</b>, so the footprint is obtainable for this parcel.")
    elif year_built:
        lines.append(
            f"Built {year_built} — predates 1977, so LADBS as-built plans may not exist. "
            f"Try the Certificate of Occupancy or permit history.")
    return "<br>".join(lines)
