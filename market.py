"""
market.py — exit pricing, measured rather than assumed.
===========================================================
PCR / Palisades.  Added 9 September 2026.

WHY THIS MODULE EXISTS

Every exit price in the model was drawn from a pooled median of Palisades sales
running June 2023 to May 2026.  That pool straddles 7 January 2025.  The fire
destroyed 6,837 structures across 23,448 acres, and the burn footprint is not
the whole of Pacific Palisades — the Riviera and the eastern blocks largely
stood.  Pooling the two sides of that line, across both sides of that date,
mixes two different markets and hides the single largest movement in the data.

WHAT WAS MEASURED

Difference-in-differences on the 330 sales in comps_database.csv, using the
Santa Monica (90402) and Brentwood (90049) sales as an out-of-footprint control
so that ordinary Westside market drift is netted out.

    log($/sf) ~ log(sf) + age + t + burn + riviera
                + post + post:burn + post:riviera

    post:burn      -17.1%   95% CI [-31.0%, -0.3%]   p = 0.046
    post:riviera    +3.1%   95% CI [-14.0%, +23.6%]  p = 0.740
    size elasticity -0.242                            p < 0.001
    new build (<=5yr) +9.4% 95% CI [-1.2%, +21.3%]   p = 0.085

    n = 330, R2 = 0.324, HC3 standard errors.
    Bootstrap, 2,000 draws: median -17.0%, 5th -28.6%, 95th -3.8%,
    P(discount is negative) = 98%.
    Stable across burn-boundary cutoffs from -118.530 to -118.545
    (-15.4% to -18.0%).

Standing homes inside the burn footprint repriced down about 17%.  Homes
outside it did not move.  Only 24 post-fire sales sit inside the footprint, so
the confidence interval is wide and the point estimate should never be quoted
without it.

THE TWO LIMITATIONS, STATED

1.  The burn footprint here is a longitude cut at -118.535, not the CAL FIRE
    perimeter.  It is a proxy.  Geocoding the comps against the published
    perimeter would replace `in_burn_zone` below and is the single highest-value
    fix to this module.  GAP.

2.  The discount is measured at the moment of maximum disruption.  Whether it
    persists to a 2029 exit is a forecast, not an observation.  Under rule 5 it
    is therefore split in two: the measured discount is the base case, and any
    recovery from it is a labelled bet defaulted to zero.  `burn_recovery` is
    that bet.  It is the mirror image of the 2028-29 scarcity thesis and the two
    must never both be switched on without saying so out loud.
"""

from dataclasses import dataclass
from typing import Optional

MARKET_VERSION = "m2.0 · 10 Sep 2026 · 1,184-sale file, land trades separated"

# =====================================================================
# CORRECTION, 10 September 2026. m1.0 reported a 17% post-fire DISCOUNT.
# That was an artifact and it is withdrawn.
#
# Redfin lists a burned lot under the PRE-FIRE house's square footage. A
# Village lot trading at $3.3M against a prior 4,488 sf home computes to
# $735/sf and reads as a cheap house. It is dirt. Checking for
# implausibly low $/sf did not catch it, because land at Palisades
# prices lands inside the plausible range for a house.
#
# 43 of the 132 post-fire Palisades sales are land trades. Removing them:
#
#   pre-fire  standing homes   n=770   $1,320/sf
#   post-fire standing homes   n= 89   $1,542/sf     (+16.9%)
#
# Difference-in-differences on standing homes only, Santa Monica and
# Brentwood as control, 1,184-sale file:
#
#   Palisades post-fire   +13.2%   95% CI [+1%, +26%]   p = 0.027
#
# Standing homes in the Palisades are worth MORE than before the fire,
# not less. The direction of the m1.0 finding was wrong, not just its
# magnitude.
# =====================================================================

FIRE_DATE = "2025-01-07"
FIRE_STRUCTURES_DESTROYED = 6837
FIRE_ACRES = 23448

# ---- exit pricing, standing homes, land trades removed
EXIT_PSF_PRE_FIRE = 1320.0
EXIT_PSF_POST_FIRE = 1542.0          # BASE CASE
POST_FIRE_EFFECT = +0.132
POST_FIRE_CI = (+0.01, +0.26)

# The $1,100/house-ft cut that separates land from houses is a proxy, and
# the exit price is sensitive to it: $1,462 at a $900 cut, $1,678 at
# $1,200. Treat $1,542 as central and $1,460-$1,680 as the range. The
# clean fix is a burned/not-burned flag per parcel. GAP.
EXIT_PSF_RANGE = (1462.0, 1678.0)

# Corroboration from two independent directions, both ~$1,500-1,600:
#   - Tal's realtor (The Agency), completed product today
#   - RTI lots on market imply $1,472-$1,929/sf at a 15% margin
#     (16150 Northfield $268/buildable ft, 865 Oreo $330,
#      14736 McKendree $499, 611 Ocampo $597)
RTI_IMPLIED_EXIT = (1472.0, 1929.0)

# ---- SIZE. This reversed too, and it matters for what to build.
# Pre-fire elasticity -0.243: bigger houses sold for less per foot.
# Post-fire elasticity +0.182 (p=0.011, n=89): bigger houses sell for
# MORE per foot. Post-fire medians by band: <3,000 $1,334;
# 3,000-4,000 $1,362; 4,000-5,000 $1,924; 5,000-6,500 $1,957; 6,500+ $1,948.
# Buyers with insurance proceeds are replacing large homes, and small
# surviving stock is not what they want. Build to the envelope.
SIZE_ELASTICITY = +0.182
SIZE_ELASTICITY_PRE_FIRE = -0.243

# ---- the land market, which did not exist before January 2025
LAND_PSF_LOT_MEDIAN = 258.0          # $/lot ft, 43 post-fire land trades
LAND_PSF_LOT_Q1 = 171.0
LAND_PSF_LOT_Q3 = 333.0

NEW_BUILD_PREMIUM_POINT = 0.094
NEW_BUILD_PREMIUM_CI = (-0.012, 0.213)
NEW_BUILD_PREMIUM_P = 0.085

BURN_DISCOUNT_POINT = 0.0            # WITHDRAWN, see correction above
BURN_DISCOUNT_P05 = 0.0
BURN_DISCOUNT_P95 = 0.0
BURN_DISCOUNT_P = 1.0

BURN_LON_CUT = -118.535
PALISADES_ZIP = 90272


def land_value(lot_sqft, quartile="median"):
    """
    What burned Palisades dirt actually trades at, from 43 post-fire land
    trades. This is a market check on any ask, independent of the
    envelope calculation.
    """
    psf = {"q1": LAND_PSF_LOT_Q1, "median": LAND_PSF_LOT_MEDIAN,
           "q3": LAND_PSF_LOT_Q3}[quartile]
    return psf * float(lot_sqft or 0)


def in_burn_zone(lat: Optional[float], lon: Optional[float],
                 zip_code: Optional[int] = None) -> Optional[bool]:
    """
    True inside the proxy burn footprint, False outside, None if unknowable.

    None matters. A lot with no coordinates is UNSCREENED, not passed — the same
    rule the gates use. Absence of a flag is not a clear flag.
    """
    if lon is None or lat is None:
        return None
    if zip_code is not None and int(zip_code) != PALISADES_ZIP:
        return False
    return lon < BURN_LON_CUT


def size_adjusted_psf(base_psf: float, base_sqft: float, target_sqft: float) -> float:
    """
    Move a $/sf figure from one house size to another along the measured
    elasticity, so a 6,200 sf comp median is not applied to a 2,700 sf build.

    Elasticity is -0.242: a 10% larger house sells for about 2.4% less per foot.
    Total price still rises with size (as sf^0.758), just sublinearly.
    """
    if not base_sqft or not target_sqft or base_sqft <= 0 or target_sqft <= 0:
        return base_psf
    return base_psf * (target_sqft / base_sqft) ** SIZE_ELASTICITY


def marginal_revenue_psf(psf_at_size: float) -> float:
    """
    Revenue earned by the NEXT square foot, which is what decides whether to
    build to the envelope. With elasticity e, total price is proportional to
    sf^(1+e), so the marginal foot earns (1+e) times the average $/sf.

    Compare against loaded marginal construction cost. At $700/sf hard plus A&E
    and contingency that is roughly $833/ft, and at Palisades pricing the two are
    close enough that maximising the envelope is value-neutral. When they are
    close, choose the smaller house: less capital at risk, shorter schedule,
    wider buyer pool.
    """
    return psf_at_size * (1.0 + SIZE_ELASTICITY)


@dataclass
class ExitPrice:
    """A priced exit with its provenance and its range attached."""
    psf: float
    psf_low: float
    psf_high: float
    basis_psf: float
    burn_zone: Optional[bool]
    discount_applied: float
    recovery_applied: float
    note: str

    def stamp(self) -> str:
        if self.burn_zone is None:
            return f"${self.psf:,.0f}/sf · burn status UNSCREENED · {self.note}"
        if not self.burn_zone:
            return f"${self.psf:,.0f}/sf · outside burn footprint · no adjustment"
        return (f"${self.psf:,.0f}/sf "
                f"(range ${self.psf_low:,.0f}-${self.psf_high:,.0f}) · "
                f"burn footprint · {self.discount_applied:+.1%} measured"
                + (f" · recovery bet {self.recovery_applied:+.1%}"
                   if self.recovery_applied else ""))


def exit_price(basis_psf: float,
               burn_zone: Optional[bool],
               burn_recovery: float = 0.0,
               apply_discount: bool = True) -> ExitPrice:
    """
    Turn a comp median into an exit price.

    basis_psf      the matched comp median, tier- and size-banded upstream
    burn_zone      True / False / None from in_burn_zone()
    burn_recovery  0.0 to 1.0. THE BET. 0.0 keeps the full measured discount to
                   exit. 1.0 assumes the burn zone returns to its pre-fire
                   relationship with the rest of the Westside. Defaults to zero
                   under rule 5 and is reported separately wherever it is used.

    When burn status is unknown the discount is applied anyway and the note says
    so, because an unverified lot should not score better than a verified one.
    """
    if not apply_discount or burn_zone is False:
        return ExitPrice(basis_psf, basis_psf, basis_psf, basis_psf,
                         burn_zone, 0.0, 0.0, "no burn adjustment")

    r = max(0.0, min(1.0, burn_recovery))
    d = BURN_DISCOUNT_POINT * (1 - r)
    lo = BURN_DISCOUNT_P05 * (1 - r)
    hi = BURN_DISCOUNT_P95 * (1 - r)

    note = ("burn status unknown, discount applied and flagged"
            if burn_zone is None else "measured post-fire repricing")

    return ExitPrice(psf=basis_psf * (1 + d),
                     psf_low=basis_psf * (1 + lo),
                     psf_high=basis_psf * (1 + hi),
                     basis_psf=basis_psf,
                     burn_zone=burn_zone,
                     discount_applied=d,
                     recovery_applied=r * -BURN_DISCOUNT_POINT,
                     note=note)


# ------------------------------------------------------- the screening metric
def breakeven_land_psf(exit_psf: float,
                       construction_psf: float = 700.0,
                       ae_pct: float = 0.05,
                       contingency_pct: float = 0.08,
                       finance_multiple: float = 1.153,
                       selling_pct: float = 0.04,
                       doc_tax_pct: float = 0.0056,
                       required_margin: float = 0.0) -> float:
    """
    Land dollars per BUILDABLE foot at which the deal returns `required_margin`.

    This is the screen that replaces ask price. Palisades land is priced per lot
    while R1 caps floor area per lot, so a $1M ask means nothing until it is
    divided by what can actually be built. Two lots at the same ask can differ
    threefold on this metric.

    Excludes ULA, which is a cliff rather than a rate and is applied on the whole
    sale price in the pro forma. Below $5.4M indexed it is zero, and most of the
    envelopes that clear this screen sell below the cliff.
    """
    net_per_foot = exit_psf * (1 - selling_pct - doc_tax_pct)
    allowed = net_per_foot / finance_multiple / (1 + required_margin)
    loaded_cost = construction_psf * (1 + ae_pct + contingency_pct)
    return allowed - loaded_cost


def land_verdict(ask: float, buildable_sqft: float, exit_psf: float,
                 construction_psf: float = 700.0,
                 required_margin: float = 0.15) -> dict:
    """Ask against breakeven, per buildable foot. The whole screen in one call."""
    if not buildable_sqft:
        return dict(priceable=False, note="No envelope computed.")
    ask_psf = ask / buildable_sqft
    be = breakeven_land_psf(exit_psf, construction_psf)
    tgt = breakeven_land_psf(exit_psf, construction_psf,
                             required_margin=required_margin)
    return dict(
        priceable=True,
        ask_land_psf=round(ask_psf),
        breakeven_land_psf=round(be),
        target_land_psf=round(tgt),
        breakeven_land_total=round(be * buildable_sqft),
        target_land_total=round(tgt * buildable_sqft),
        headroom_pct=(be * buildable_sqft / ask - 1) if ask else 0.0,
        clears_breakeven=ask_psf <= be,
        clears_target=ask_psf <= tgt,
    )
