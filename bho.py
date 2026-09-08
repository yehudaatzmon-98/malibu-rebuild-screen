"""
Baseline Hillside Ordinance — Maximum Residential Floor Area.
=============================================================

WHY THIS EXISTS

Until 8 September 2026 `jurisdiction.eo8_zoning_envelope` computed the EO8 envelope
as `lot_sqft x 0.45` for every City of Los Angeles lot, and returned None with a note
whenever a hillside flag was set. Two things were wrong with that.

    1. 0.45 is not R1's ratio in a Hillside Area. Under LAMC 12.21 C.10(b) the R1 FAR
       runs from 0.50 on the flattest band down to 0.00 above 100% slope.

    2. Returning None on hillside lots dropped 77 of 132 Palisades lots out of the
       ranking entirely, when in fact the ordinance guarantees a FLOOR on every one of
       them. A hillside lot is not unscoreable. It is a range.

Two documents forced this. The 2022 Certificate of Occupancy on 1228 Las Lomas Pl
reads Zone RE11-1, Baseline Hillside Ordinance Yes. The 2022 permit on 623 N
Marquette St reads Zone R1-1, Baseline Hillside Ordinance Yes. Same ordinance, two
different zones, and the model was applying one hardcoded number to both.

WHAT THE ORDINANCE ACTUALLY SAYS

Maximum Residential Floor Area is the sum, over slope bands, of the area of the lot
in each band multiplied by that band's FAR for the lot's zone (Table 2). Regardless
of what that produces, the maximum may be at least a percentage of lot size per
Table 4, or 1,000 sqft, whichever is greater — the Guaranteed Minimum. A bonus of
+20% on the Table 2 result, or +30% where the Guaranteed Minimum is used, is
available through any one of seven design options.

DO THE EMERGENCY ORDERS SUSPEND THIS? NO.

EO1 and EO8 waive REVIEW, not standards. EO8 lets a non-like-for-like project that
COMPLIES WITH ZONING bypass local Coastal Act and CEQA review. BHO is zoning. What
the orders waive is procedural: Hillside Ordinance review, Specific Plan review,
zoning overlay review, the BHO street-widening requirement, haul route and tree
hearings. LADBS still enforces the floor area cap. So this module is the ceiling on
the EO8 path, not a formality.

Reference: LAMC 12.21 C.10; City of Los Angeles Department of City Planning,
"Baseline Hillside Ordinance — A Comprehensive Guide" (Ordinance No. 181,624).
"""
from __future__ import annotations
from typing import Optional

# Table 2 — Single-Family Zone Hillside Area Residential Floor Area Ratios.
# Bands are (low %, high %) inclusive-exclusive on the upper bound.
SLOPE_BANDS = ((0, 15), (15, 30), (30, 45), (45, 60), (60, 100), (100, None))

FAR_TABLE = {
    #            0-15  15-30 30-45 45-60 60-100 100+
    "R1":   (0.50, 0.45, 0.40, 0.35, 0.30, 0.00),
    "RS":   (0.45, 0.40, 0.35, 0.30, 0.25, 0.00),
    "RE9":  (0.40, 0.35, 0.30, 0.25, 0.20, 0.00),
    "RE11": (0.40, 0.35, 0.30, 0.25, 0.20, 0.00),
    "RE15": (0.35, 0.30, 0.25, 0.20, 0.15, 0.00),
    "RE20": (0.35, 0.30, 0.25, 0.20, 0.15, 0.00),
    "RE40": (0.35, 0.30, 0.25, 0.20, 0.15, 0.00),
    "RA":   (0.25, 0.20, 0.15, 0.10, 0.05, 0.00),
}

# Table 4 — Guaranteed Minimum Residential Floor Area, as a share of lot size.
# Floored at 1,000 sqft regardless of zone or lot size.
GUARANTEED_MIN = {
    "R1": 0.25, "RS": 0.23, "RE9": 0.20, "RE11": 0.20,
    "RE15": 0.18, "RE20": 0.18, "RE40": 0.18, "RA": 0.13,
}
GUARANTEED_MIN_FLOOR_SQFT = 1_000

# Table 5 — Maximum envelope height, Height District 1 / 1L / 1VL.
HEIGHT_FT = {
    #        pitched (roof slope >= 25%), flat (< 25%)
    "R1":   (33, 28), "RS": (33, 28), "RE9": (33, 28), "RE11": (36, 30),
    "RE15": (36, 30), "RE20": (36, 30), "RE40": (36, 30), "RA": (36, 30),
}

# Table 7 — maximum by-right grading, cubic yards. The formula is 500 CY plus 5% of
# lot size in CY, capped by zone.
GRADING_CAP_CY = {
    "R1": 1000, "RS": 1100, "RE9": 1200, "RE11": 1400,
    "RE15": 1600, "RE20": 2000, "RE40": 3300, "RA": 1800,
}

BONUS_ON_BANDS = 0.20      # 12.21 C.10(b)(3)
BONUS_ON_GUARANTEED = 0.30

BONUS_OPTIONS = (
    "Proportional Stories — upper storeys <= 75% of base floor. Flat pads only.",
    "Front Facade Stepback — 25% of building width stepped back 20% of depth.",
    "Cumulative Side Yards — combined side yards >= 25% of lot width.",
    "18-Foot Envelope Height — caps the building at 18 ft.",
    "Multiple Structures — no single building covers more than 20% of the lot.",
    "Minimal Grading — total grading <= 10% of lot size in CY or 1,000 CY. Only "
    "where at least 60% of the lot is 30%+ slope.",
    "Green Building — new one-family dwelling meeting Tier 1 of the LA Green "
    "Building Code. THE ONLY OPTION THAT DOES NOT CONSTRAIN MASSING, and therefore "
    "the default assumption for a ground-up spec build.",
)


def normalise_zone(zone: Optional[str]) -> Optional[str]:
    """'RE11-1', 'R1-1-H', 'r1' -> 'RE11', 'R1', 'R1'."""
    if not zone:
        return None
    z = str(zone).upper().strip().split("-")[0].replace(" ", "")
    return z if z in FAR_TABLE else None


def exempt_areas(rfa: float) -> dict:
    """
    Area that does NOT count against RFA and so is additive to the saleable house.

    These are the reason a lot capped at 2,500 sqft of RFA can still deliver a house
    that markets materially larger. They are not upside to be assumed; each one has
    to survive a design, and the basement in particular depends on the topography.
    """
    porch = max(0.05 * rfa, 250)
    return dict(
        required_covered_parking=400,   # 200 sqft x 2 required spaces
        covered_porch=round(porch),     # 5% of RFA, need not be less than 250
        detached_accessory=400,         # <=200 sqft each, 400 sqft combined cap
        note=("Lattice-roof porches, patios and breezeways are exempt without limit. "
              "A BASEMENT is exempt in a Hillside Area when the upper surface of the "
              "floor or roof above it is no more than 3 ft above the lower of finished "
              "or natural grade for at least 60% of the exterior basement perimeter, "
              "and cut under a building footprint is also exempt from the grading "
              "limits. On an ascending-slope lot that is achievable by design and it "
              "is the single largest lever on saleable area. It is an ASSUMPTION until "
              "an architect confirms it against this lot's topography, and it must not "
              "be folded into a base case before then."))


def rfa_from_slope_bands(zone: str, bands_sqft: dict) -> Optional[float]:
    """
    Table 3. `bands_sqft` maps a band index 0..5 (or its low bound as an int) to the
    lot area in that band. Returns the summed Residential Floor Area.
    """
    z = normalise_zone(zone)
    if not z:
        return None
    fars = FAR_TABLE[z]
    total = 0.0
    for key, area in (bands_sqft or {}).items():
        if area is None:
            continue
        i = int(key)
        if i > 5:  # caller passed the band's low bound (0/15/30/45/60/100)
            i = {0: 0, 15: 1, 30: 2, 45: 3, 60: 4, 100: 5}.get(i)
            if i is None:
                continue
        total += float(area) * fars[i]
    return total


def bho_rfa(zone: Optional[str], lot_sqft: Optional[float],
            bands_sqft: Optional[dict] = None,
            bonus: bool = True) -> dict:
    """
    Maximum Residential Floor Area under the Baseline Hillside Ordinance.

    With `bands_sqft` from a stamped Slope Analysis Map this returns one number.
    Without it, it returns the FULL RANGE the ordinance permits: the Guaranteed
    Minimum as a hard floor and the flattest-band result as a ceiling. That is the
    honest output when the slope is unknown, and it is still enough to underwrite a
    downside case, which `None` never was.

    `bonus=True` assumes the Green Building option is taken, since it is the only one
    of the seven that does not constrain massing and a ground-up spec build meeting
    Tier 1 of the LA Green Building Code is ordinary. Set it False for a case that
    claims no bonus at all.
    """
    z = normalise_zone(zone)
    if not z:
        return dict(ok=False, note=(
            "No recognised single-family zone. BHO applies to R1, RS, RE9, RE11, "
            "RE15, RE20, RE40 and RA lots designated Hillside Area. Get the zone "
            "string from ZIMAS or from the PARCEL INFORMATION block of any "
            "Certificate of Occupancy issued from roughly 2008 onward."))
    if not lot_sqft or lot_sqft <= 0:
        return dict(ok=False, note="No lot area. Lot area is the whole input.")

    fars = FAR_TABLE[z]
    guaranteed = max(GUARANTEED_MIN[z] * lot_sqft, GUARANTEED_MIN_FLOOR_SQFT)

    def _with_bonus(band_result: float) -> float:
        """Take the better of the banded result +20% and the guaranteed minimum +30%."""
        if not bonus:
            return max(band_result, guaranteed)
        return max(band_result * (1 + BONUS_ON_BANDS),
                   guaranteed * (1 + BONUS_ON_GUARANTEED))

    if bands_sqft:
        banded = rfa_from_slope_bands(z, bands_sqft) or 0.0
        rfa = _with_bonus(banded)
        covered = sum(float(v or 0) for v in bands_sqft.values())
        notes = [f"<b>Slope-band RFA {rfa:,.0f} sqft</b> for {z} on a {lot_sqft:,.0f} "
                 f"sqft lot (banded {banded:,.0f}, guaranteed minimum "
                 f"{guaranteed:,.0f}{', bonus applied' if bonus else ''})."]
        if abs(covered - lot_sqft) > 0.02 * lot_sqft:
            notes.append(
                f"The slope bands supplied total {covered:,.0f} sqft against a lot of "
                f"{lot_sqft:,.0f} sqft. They should cover the whole lot. Check the map.")
        return dict(ok=True, zone=z, exact=True, rfa=round(rfa),
                    rfa_min=round(rfa), rfa_max=round(rfa),
                    guaranteed_min=round(guaranteed), banded=round(banded),
                    bonus_applied=bonus, exempt=exempt_areas(rfa),
                    height_ft=HEIGHT_FT[z], lot_coverage=0.40,
                    grading_cy=min(500 + 0.05 * lot_sqft, GRADING_CAP_CY[z]),
                    note="<br>".join(notes))

    # No slope analysis. Bound it.
    floor = _with_bonus(0.0)                      # every band could be 100%+
    ceiling = _with_bonus(fars[0] * lot_sqft)     # every band could be 0-15%
    per_band = {f"{lo}-{hi if hi else '+'}%": round(_with_bonus(f * lot_sqft))
                for (lo, hi), f in zip(SLOPE_BANDS, fars)}

    return dict(
        ok=True, zone=z, exact=False,
        rfa=None, rfa_min=round(floor), rfa_max=round(ceiling),
        guaranteed_min=round(guaranteed), by_band=per_band, bonus_applied=bonus,
        exempt=exempt_areas(floor),
        height_ft=HEIGHT_FT[z], lot_coverage=0.40,
        grading_cy=min(500 + 0.05 * lot_sqft, GRADING_CAP_CY[z]),
        note=(f"<b>{z} in a Hillside Area: RFA is between {floor:,.0f} and "
              f"{ceiling:,.0f} sqft</b> on a {lot_sqft:,.0f} sqft lot. The floor is the "
              f"Guaranteed Minimum ({GUARANTEED_MIN[z]:.0%} of lot area, or 1,000 sqft) "
              f"and holds even if the entire lot exceeds 100% slope. The ceiling assumes "
              f"the whole lot sits in the flattest band."
              f"{' Both include the floor-area bonus.' if bonus else ''}<br>"
              f"<span class='cite'>Rank on the floor and treat everything above it as "
              f"unpriced. A stamped Slope Analysis Map from a California civil engineer "
              f"or licensed surveyor, verified by City Planning on the Slope Analysis and "
              f"Maximum Residential Floor Area Verification Form, collapses this to one "
              f"number. NavigateLA with the APN and the level-curves layer gives a rough "
              f"read for free before paying for the survey.</span>"))
