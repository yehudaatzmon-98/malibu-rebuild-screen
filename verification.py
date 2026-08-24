"""
Verification and margin-over-market.
====================================

WHY THIS MODULE EXISTS

On 21 August 2026 we pulled LADBS records on five candidate lots. The tool's ranking
inverted completely. Every single prior-square-footage figure in the working sheet
was wrong, and every one was wrong in the same direction — overstated, making the
deal look better than it was:

    627 Marquette   sheet 3,399   ACTUAL 1,440   (sheet figure was the zoning
                                                  buildable, not the prior house)
    865 Oreo        sheet 5,000   ACTUAL 4,202   (certified, two C of Os)
    16815 Livorno   sheet 7,335   ACTUAL 4,666   (certified, 2018 build)
    878 Hartzell    sheet 3,910   ACTUAL 3,335   (certified, 2010 build)
    955 Fiske       sheet 5,000   agent-stated, still unverified

Five for five. The lot that ranked worst on unverified numbers (Marquette) is the
best on verified ones. The lot that looked competitive (Hartzell) is unbuildable
economics.

So the tool had a structural flaw: it treated a number typed into a spreadsheet as
equivalent to a number on a Certificate of Occupancy. This module fixes that in two
ways.

    1. PROVENANCE. Every square-footage figure carries where it came from, and the
       ranking demotes lots whose economics rest on unverified inputs. A lot you
       can act on beats a lot that merely looks good.

    2. MARGIN OVER MARKET. The headline metric becomes the breakeven exit price
       expressed as a percentage above or below the matched comparable median —
       "this lot needs to beat the market by 5%" rather than "this lot returns 26%".
       Return-on-cost moves with whatever exit price you assume. Margin over market
       does not: it compares a cost fact against a sales fact, and it is the number
       that actually separated the five properties.
"""
from __future__ import annotations
import urllib.parse
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------- provenance
# Ordered worst to best. The label is what the user sees; the weight is how much
# the ranking trusts economics built on it.
PROVENANCE = {
    "NONE":      dict(rank=0, weight=0.00, label="no figure",
                      note="No prior square footage from any source."),
    "SHEET":     dict(rank=1, weight=0.35, label="spreadsheet — UNVERIFIED",
                      note="Typed into a working sheet. Every one of these we have "
                           "checked was wrong, and always overstated."),
    "LISTING":   dict(rank=2, weight=0.45, label="listing / agent — unverified",
                      note="Agent-stated or from marketing copy. Often includes "
                           "uncounted basement or unpermitted area."),
    "ASSESSOR":  dict(rank=3, weight=0.65, label="county assessor",
                      note="A taxation record, not a survey. Frequently excludes "
                           "below-grade area and lags permitted additions."),
    "PERMIT":    dict(rank=4, weight=0.90, label="original building permit",
                      note="Dimensions from the issued permit. Authoritative on what "
                           "was approved."),
    "CERTIFIED": dict(rank=5, weight=1.00, label="Certificate of Occupancy — CERTIFIED",
                      note="The floor area the City certified as lawfully completed. "
                           "This is the number rebuild rights attach to."),
}


@dataclass
class Verified:
    """A square-footage figure with its provenance attached."""
    sqft: Optional[float]
    source: str = "NONE"
    height_ft: Optional[float] = None
    height_source: str = "NONE"
    note: str = ""

    @property
    def weight(self) -> float:
        return PROVENANCE.get(self.source, PROVENANCE["NONE"])["weight"]

    @property
    def is_verified(self) -> bool:
        return self.source in ("PERMIT", "CERTIFIED")

    @property
    def label(self) -> str:
        return PROVENANCE.get(self.source, PROVENANCE["NONE"])["label"]


def ladbs_links(address: Optional[str]) -> dict:
    """
    Deep links into the LADBS record for one address, in the order they should be
    opened. This is the four-click path that settled all five properties.
    """
    enc = urllib.parse.quote_plus(str(address).strip()) if address else ""
    return {
        "1. Find the parcel": "https://www.ladbs.org/services/check-status/"
                              "building-permit-and-inspection-status"
                              + (f"  (search: {address})" if address else ""),
        "2. Permit Information": "Look for BLDG-NEW and any BLDG-ADDITION. Note the "
                                 "COFO number in the right-hand column.",
        "3. Certificate of Occupancy": "Open the PDF. Read Floor Area (ZC), Stories, "
                                       "Height (ZC). This is the number.",
        "4. Parcel Information (page 2)": "Free with the C of O: lot size, lot type, "
                                          "Coastal Zone, Hillside Ordinance, ESA, fire "
                                          "district, easements.",
        "Records request (if blank)": "records.ladbs@lacity.org — 5-7 working days, free.",
        "ZIMAS cross-check": "https://zimas.lacity.org/"
                             + (f"  (search: {address})" if address else ""),
    }


# ---------------------------------------------------- margin over market
def margin_over_market(breakeven_psf: Optional[float],
                       comp_median_psf: Optional[float],
                       comp_new_build_psf: Optional[float] = None) -> Optional[dict]:
    """
    The headline metric.

    Return-on-cost depends entirely on the exit price you assume, and the exit price
    is the least knowable input in the model. Two lots can show the same ROC at
    $1,700/sf and behave completely differently at $1,400.

    Margin over market avoids that. It asks a single question:

        HOW FAR ABOVE THE MARKET'S OWN MEDIAN DOES THIS LOT HAVE TO SELL
        JUST TO RETURN ZERO?

    Everything on the cost side — land, construction, contingency, interest, transfer
    tax, selling costs — collapses into the breakeven. Everything on the revenue side
    collapses into the matched comparable median. One number against one number.

    Worked from the five verified lots:

        627 Marquette   breakeven $1,310  vs median $1,246  ->  needs +5%   GOOD
        955 Fiske       breakeven $1,413  vs median $1,246  ->  needs +13%
        865 Oreo        breakeven $1,466  vs median $1,246  ->  needs +18%
        16815 Livorno   breakeven $1,582  vs median $1,246  ->  needs +27%
        878 Hartzell    breakeven $1,726  vs median $1,246  ->  needs +39%  DEAD

    A lot that breaks even BELOW the median has margin before the market has to do
    anything for you. That is the only kind of deal worth being the first one.
    """
    if not breakeven_psf or not comp_median_psf:
        return None
    margin = breakeven_psf / comp_median_psf - 1
    vs_new = (breakeven_psf / comp_new_build_psf - 1) if comp_new_build_psf else None

    if margin <= 0:
        tier, verdict = "STRONG", (
            "Breaks even BELOW the market median. The market does not have to do "
            "anything for this deal to work.")
    elif margin <= 0.08:
        tier, verdict = "GOOD", (
            "Needs the market to beat its own median by a small margin. New "
            "construction normally clears this on the premium alone.")
    elif margin <= 0.20:
        tier, verdict = "TIGHT", (
            "Needs a meaningfully above-median exit. Works if the new-build premium "
            "holds and the market is firm, but there is little room for error.")
    elif margin <= 0.35:
        tier, verdict = "STRETCH", (
            "Needs an exit near the top of what these streets have recorded. This is "
            "a bet on the market, not on the acquisition.")
    else:
        tier, verdict = "NO", (
            "Needs an exit the recorded sales do not support. No realistic "
            "negotiation on price closes a gap this size.")

    return dict(margin=margin, tier=tier, verdict=verdict,
                breakeven=round(breakeven_psf), median=round(comp_median_psf),
                vs_new_build=vs_new,
                phrase=(f"breaks even at ${breakeven_psf:,.0f}/sf against a comparable "
                        f"median of ${comp_median_psf:,.0f} — "
                        f"{'needs to beat the market by ' + format(margin, '.0%') if margin > 0 else format(-margin, '.0%') + ' of margin before the market has to move'}"))


def confidence_note(v: Verified, jurisdiction: str = "CITY_OF_LA") -> str:
    """What the user should understand about the number the economics rest on."""
    p = PROVENANCE.get(v.source, PROVENANCE["NONE"])
    if v.is_verified:
        head = (f"<b style='color:#1f5c2e'>Prior area {v.sqft:,.0f} sf — "
                f"{p['label']}.</b>")
        body = p["note"]
        if v.height_ft:
            body += (f" Prior height {v.height_ft:.0f} ft, which sets the EO1 cap at "
                     f"{v.height_ft*1.10:.1f} ft.")
        return head + " " + body
    head = (f"<b style='color:#7a2518'>Prior area {v.sqft:,.0f} sf — {p['label']}.</b>"
            if v.sqft else "<b style='color:#7a2518'>No prior area.</b>")
    return (head + " " + p["note"] +
            "<br><b>Every unverified figure we have checked was overstated.</b> Pull "
            "the Certificate of Occupancy before this ranking is acted on — it is free "
            "and takes about ten minutes.")


def rank_score(margin: Optional[float], weight: float,
               has_height: bool = False) -> Optional[float]:
    """
    Sort key. Lower is better.

    Margin over market drives it. Unverified inputs are penalised, because a lot you
    can act on is worth more than a lot that merely looks good — and because on the
    evidence, unverified figures move the wrong way when checked.

    A missing prior height carries a small penalty of its own: on Marquette the 15 ft
    prior height foreclosed the entire EO1 route, and nothing else in the record
    would have revealed it.
    """
    if margin is None:
        return None
    penalty = (1.0 - weight) * 0.25          # up to +25 percentage points of doubt
    if not has_height:
        penalty += 0.02
    return margin + penalty
