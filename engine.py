"""
Money engine — the "will it make money" half of the funnel.
===========================================================

This consumes the screener's output (jurisdiction, buildable envelope, entitlement
status) and answers: at that envelope, in that market, does the trade work?

TWO RULES IT WILL NOT BREAK, because breaking them is how the last model lied:

  1. COMPS ARE JURISDICTION-SEGMENTED AND NEVER BLENDED. Malibu beachfront and
     Palisades are different markets under different rulebooks. A Malibu lot is
     NEVER priced off Palisades comps. Right now the loaded comp set is Palisades
     only (263 sold sales), so Malibu lots return NO BASIS rather than a borrowed
     number. That's the segmentation rule enforced by absence, and it's correct.

  2. IT OUTPUTS A RANGE AND "WHAT YOU'D HAVE TO BELIEVE," NEVER A SINGLE VERDICT.
     The comps don't reconcile — three estimates of the same lot spanned 2.4x in
     the model teardown. A single Strong Buy would be false confidence. The engine
     ranks (which is robust) and shows the arithmetic (which is honest), and lets
     the human decide.

The size->$/sqft relationship is real and non-monotonic in this market: small
homes carry high $/sqft (land across few feet), it falls through mid-size, and
rises again at the 6,000+ trophy tier. So the matcher MUST match on finished size
or it systematically misprices. That is the single most important thing the
matcher does.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ------------------------------------------------------------------ assumptions
def ula_tax(sale_price: float, enabled: bool = True) -> dict:
    """
    Measure ULA — the LA 'mansion tax'. Missing from the model until now, and it is
    not small.

    RATES (thresholds indexed to Chained CPI each 1 July; these are the tiers in
    force for transactions closing after 30 June 2026):
        under $5,400,000        0%
        $5,400,000-$10,899,999  4.0%
        $10,900,000 and above   5.5%

    Two things people get wrong, both of which matter here:

    1. IT APPLIES TO THE ENTIRE SALE PRICE, not just the slice above the threshold.
       A $5.4M sale owes $216,000. A $5,399,999 sale owes nothing. That is a cliff,
       not a ramp, and it is worth real money on exits that land near the line.

    2. It is on top of the existing documentary transfer taxes — 0.45% City of LA
       plus 0.11% County = 0.56% — which apply at every price.

    Seller pays at closing, on gross price, not on gain. Combined with a ~5% broker
    and closing load, an exit above the threshold really does shed close to 10%.

    REPEAL RISK, and it cuts our way: the Local Taxpayer Protection Act was certified
    on 3 May 2026 for the 3 November 2026 statewide ballot. If it passes, ULA is
    replaced by a 0.05% statewide cap. Our exits are 2028-29, so this is genuinely
    uncertain — which is why it is a switch, not a hardcode. Model it ON as the
    conservative case.
    """
    if not sale_price or sale_price <= 0:
        return dict(rate=0.0, tax=0.0, tier="none", doc_tax=0.0, total=0.0, near_cliff=False)
    doc = sale_price * 0.0056  # City 0.45% + County 0.11%, applies at any price
    if not enabled:
        return dict(rate=0.0, tax=0.0, tier="ULA off", doc_tax=doc, total=doc,
                    near_cliff=False)
    if sale_price >= 10_900_000:
        rate, tier = 0.055, "5.5% (over $10.9M)"
    elif sale_price >= 5_400_000:
        rate, tier = 0.040, "4% ($5.4M-$10.9M)"
    else:
        rate, tier = 0.0, "under $5.4M — exempt"
    tax = sale_price * rate
    # flag exits sitting just over a threshold, where pricing DOWN nets more
    near = False
    for thresh, r in ((5_400_000, 0.040), (10_900_000, 0.055)):
        if thresh <= sale_price <= thresh * (1 + r + 0.005):
            near = True
    return dict(rate=rate, tax=round(tax), tier=tier, doc_tax=round(doc),
                total=round(tax + doc), near_cliff=near)


def cliff_advice(sale_price: float) -> Optional[str]:
    """
    Where an exit lands just above a ULA threshold, selling for LESS nets MORE,
    because the tax hits the whole price rather than the excess. Worth surfacing:
    it is free money and it is easy to miss.
    """
    for thresh, rate in ((5_400_000, 0.040), (10_900_000, 0.055)):
        if thresh <= sale_price <= thresh * (1 + rate + 0.005):
            below = thresh - 1_000
            net_at = sale_price - sale_price * rate
            net_below = below - (below * 0.055 if below >= 10_900_000 else
                                 below * 0.040 if below >= 5_400_000 else 0)
            if net_below > net_at:
                gain = net_below - net_at
                return (f"<b>ULA threshold cliff.</b> At ${sale_price:,.0f} the tax is "
                        f"{rate:.1%} of the <i>whole</i> price (${sale_price*rate:,.0f}). "
                        f"Pricing at ${below:,.0f} instead nets about "
                        f"<b>${gain:,.0f} more</b>. The tax is a cliff, not a ramp — "
                        f"worth designing the exit around.")
    return None


@dataclass
class Assumptions:
    """
    The fixed, versioned yardstick. Change one and everything re-scores together,
    so a lot scored today stays comparable to one scored last week. The version
    string stamps every output.
    """
    construction_psf: float = 1000.0      # Tal confirmed $1,000 fully loaded
    contingency_pct: float = 0.08         # a spec build with zero contingency isn't a pro forma
    carrying_rate: float = 0.03           # annual, on land + half the construction draw
    selling_cost_pct: float = 0.05        # broker + closing on the sale
    appreciation_pct: float = 0.03        # forward escalation — biggest unknown, kept modest
    new_build_premium: float = 0.10       # brand-new over the resale comps
    # THE SCARCITY BET — deliberately zero in the base case.
    #
    # The thesis is that by 2028-29 a rebuilt Palisades is supply-constrained and a
    # finished house commands more than today's comps imply. That may well be true.
    # It is also, today, a forecast rather than an observation: Palisades sales
    # through mid-2026 show roughly flat pricing (~+1.5%/yr on size-controlled
    # medians), which is BELOW the 3% appreciation already assumed.
    #
    # So it lives here, separately, at zero. The base case contains only what the
    # data supports. Turn it on to see the upside case, and it stays labelled as a
    # bet everywhere it shows up — an LP can argue with the bet without the
    # measured part being contaminated by it.
    scarcity_premium: float = 0.00
    # Measure ULA. ON by default — it's real today and the repeal vote is a coin flip.
    apply_ula: bool = True
    hold_years_express: float = 1.5       # like-for-like / express permit
    hold_years_standard: float = 3.0      # CDP / standard track
    version: str = "v1.2"

    def stamp(self) -> str:
        s = (f"{self.version} · ${self.construction_psf:,.0f}/sf · "
             f"cont {self.contingency_pct:.0%} · carry {self.carrying_rate:.0%} · "
             f"sell {self.selling_cost_pct:.0%} · appr {self.appreciation_pct:.0%} · "
             f"premium {self.new_build_premium:.0%}"
             f"{' · ULA on' if self.apply_ula else ' · ULA OFF'}")
        if self.scarcity_premium:
            s += f" · SCARCITY BET +{self.scarcity_premium:.0%}"
        return s


# ------------------------------------------------------------------ comp market
MALIBU_CITIES = {"MALIBU"}
PALISADES_CITIES = {"PACIFIC PALISADES", "LOS ANGELES", "SANTA MONICA"}


def _haversine(lat1, lon1, lat2, lon2):
    """Miles between two points."""
    if any(pd.isna(x) for x in (lat1, lon1, lat2, lon2)):
        return None
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(a))


class CompMarket:
    """
    Holds the sold-comp database and matches a subject lot to comparable sales
    WITHIN its own jurisdiction only.
    """
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.df["sold_date"] = pd.to_datetime(self.df["sold_date"], errors="coerce")
        # normalise city for jurisdiction routing
        self.df["_city_u"] = self.df["city"].str.upper().str.strip()

    def _pool(self, jurisdiction: str) -> pd.DataFrame:
        """The comp pool for a jurisdiction. Malibu is deliberately empty here."""
        if jurisdiction == "MALIBU":
            return self.df[self.df["_city_u"].isin(MALIBU_CITIES)]
        return self.df[self.df["_city_u"].isin(PALISADES_CITIES)]

    def match(self, jurisdiction: str, target_sqft: float,
              lat: Optional[float] = None, lon: Optional[float] = None,
              k: int = 6, asof_year: int = 2026) -> dict:
        """
        Score-weighted $/sqft from the k best-matching sold comps in-jurisdiction.

        Match score weights: SIZE first (the non-monotonic $/sqft curve makes size
        the dominant driver), then recency, then distance. Neighborhood is nearly
        constant in this data so it isn't used.
        """
        pool = self._pool(jurisdiction)
        if len(pool) == 0:
            return dict(basis=None, n=0, comps=[],
                        note=(f"NO COMP BASIS — the loaded database has no {jurisdiction} "
                              f"sales. This market can't be priced from the current comps. "
                              f"Supply {jurisdiction} sold comps, or use a tagged manual "
                              f"override (e.g. the David $4,500/sf beachfront point)."))
        rows = []
        for _, c in pool.iterrows():
            csqft = c["square_feet"]
            if not csqft or csqft <= 0:
                continue
            # size score: 1.0 at exact match, decaying with proportional gap
            size_gap = abs(csqft - target_sqft) / max(target_sqft, 1)
            size_score = 1.0 / (1.0 + 2.0 * size_gap)
            # recency: newer is better, ~3-year window
            yrs = asof_year - (c["sold_date"].year if pd.notna(c["sold_date"]) else asof_year - 3)
            rec_score = max(0.2, 1.0 - 0.18 * max(0, yrs))
            # distance if we have coords
            dist = _haversine(lat, lon, c["latitude"], c["longitude"]) if lat and lon else None
            dist_score = 1.0 if dist is None else 1.0 / (1.0 + dist)
            score = 0.55 * size_score + 0.30 * rec_score + 0.15 * dist_score
            rows.append((score, c, dist))
        if not rows:
            return dict(basis=None, n=0, comps=[], note="No usable comps (missing sizes).")
        rows.sort(key=lambda r: r[0], reverse=True)
        top = rows[:k]
        wsum = sum(s for s, _, _ in top)
        basis = sum(s * c["price_per_square_foot"] for s, c, _ in top) / wsum
        comps = [dict(
            address=c["address"], city=c["city"],
            sold=c["sold_date"].date().isoformat() if pd.notna(c["sold_date"]) else "?",
            price=int(c["price"]), sqft=int(c["square_feet"]),
            psf=int(c["price_per_square_foot"]),
            dist_mi=round(d, 2) if d is not None else None,
            weight=round(s / wsum, 3),
        ) for s, c, d in top]
        # honest spread: the min and max $/sqft among the matched set
        psfs = [c["price_per_square_foot"] for _, c, _ in top]
        return dict(basis=round(basis), n=len(top), comps=comps,
                    low=int(min(psfs)), high=int(max(psfs)),
                    note=None)


# ------------------------------------------------------------------ the pro forma
@dataclass
class ProForma:
    buildable_sqft: float
    land_cost: float
    exit_psf_basis: Optional[float]
    jurisdiction: str
    a: Assumptions
    express: bool = True
    comp_low: Optional[float] = None
    comp_high: Optional[float] = None

    def _run_one(self, exit_psf: float) -> dict:
        hold = self.a.hold_years_express if self.express else self.a.hold_years_standard
        construction = self.buildable_sqft * self.a.construction_psf
        contingency = construction * self.a.contingency_pct
        # carry on land for the whole hold + half the construction draw
        carry = (self.land_cost + 0.5 * construction) * self.a.carrying_rate * hold
        total_cost = self.land_cost + construction + contingency + carry
        # exit: comp basis, escalated forward, plus new-build premium
        escalated = exit_psf * ((1 + self.a.appreciation_pct) ** hold)
        premium = escalated * (1 + self.a.new_build_premium)
        # the scarcity bet is applied LAST and tracked separately, so the measured
        # part of the exit price is always recoverable from the output
        premium_measured = premium
        premium = premium * (1 + self.a.scarcity_premium)
        gross_sale = premium * self.buildable_sqft
        # transfer taxes come off the gross, alongside broker/closing
        _ula = ula_tax(gross_sale, enabled=self.a.apply_ula)
        net_sale = gross_sale * (1 - self.a.selling_cost_pct) - _ula["total"]
        profit = net_sale - total_cost
        roc = profit / total_cost if total_cost else 0
        return dict(
            exit_psf=round(exit_psf), effective_psf=round(premium),
            effective_psf_measured=round(premium_measured),
            scarcity_applied=self.a.scarcity_premium,
            construction=round(construction), contingency=round(contingency),
            carry=round(carry), total_cost=round(total_cost),
            gross_sale=round(gross_sale), net_sale=round(net_sale),
            ula_tax=_ula["tax"], ula_tier=_ula["tier"], doc_tax=_ula["doc_tax"],
            ula_total=_ula["total"], near_cliff=_ula["near_cliff"],
            profit=round(profit), roc=roc, hold=hold,
        )

    def run(self) -> dict:
        if self.exit_psf_basis is None:
            return dict(priceable=False,
                        note="No comp basis in-jurisdiction. Eligible and buildable, "
                             "but not priceable from the loaded comps.")
        base = self._run_one(self.exit_psf_basis)
        # range from the matched comps' own low/high, not a made-up band
        lo = self._run_one(self.comp_low) if self.comp_low else None
        hi = self._run_one(self.comp_high) if self.comp_high else None
        return dict(priceable=True, base=base, low=lo, high=hi,
                    signal=_signal(base["roc"]))


def _signal(roc: float) -> str:
    if roc >= 0.35:
        return "STRONG"
    if roc >= 0.20:
        return "BUY"
    if roc >= 0.08:
        return "MAYBE"
    return "PASS"


def sensitivity(pf: ProForma, cost_range=(800, 900, 1000, 1100),
                appr_range=(0.0, 0.03, 0.06)) -> list:
    """Return-on-cost grid across construction cost x appreciation. Shows whether
    the RANKING is robust even where the SIGNAL is assumption-dependent."""
    if pf.exit_psf_basis is None:
        return []
    grid = []
    for cost in cost_range:
        row = {"construction_psf": cost, "cells": []}
        for appr in appr_range:
            a2 = Assumptions(**{**pf.a.__dict__, "construction_psf": cost,
                                "appreciation_pct": appr})
            pf2 = ProForma(pf.buildable_sqft, pf.land_cost, pf.exit_psf_basis,
                           pf.jurisdiction, a2, pf.express)
            row["cells"].append(dict(appr=appr, roc=pf2._run_one(pf.exit_psf_basis)["roc"]))
        grid.append(row)
    return grid


def what_youd_have_to_believe(pf: ProForma, target_roc: float = 0.20) -> dict:
    """Instead of asserting a number, invert it: what exit $/sqft does the lot need
    to clear a target return, and how does that compare to the comp basis?"""
    if pf.exit_psf_basis is None:
        return dict(ok=False)
    # binary search the exit_psf that yields target_roc
    lo, hi = 100, 20000
    for _ in range(40):
        mid = (lo + hi) / 2
        # invert premium+escalation back out of _run_one's exit_psf input
        roc = pf._run_one(mid)["roc"]
        if roc < target_roc:
            lo = mid
        else:
            hi = mid
    needed = (lo + hi) / 2
    return dict(ok=True, needed_exit_psf=round(needed),
                comp_basis=round(pf.exit_psf_basis),
                gap=round((needed / pf.exit_psf_basis - 1) * 100))


def _roc_with(pf: ProForma, *, land=None, constr=None, build=None, exit_psf=None) -> float:
    """Re-run the pro forma with one lever changed. Used by the solver below."""
    a2 = pf.a
    if constr is not None:
        a2 = Assumptions(**{**pf.a.__dict__, "construction_psf": float(constr)})
    pf2 = ProForma(
        float(build) if build is not None else pf.buildable_sqft,
        float(land) if land is not None else pf.land_cost,
        float(exit_psf) if exit_psf is not None else pf.exit_psf_basis,
        pf.jurisdiction, a2, pf.express)
    return pf2._run_one(float(exit_psf) if exit_psf is not None else pf.exit_psf_basis)["roc"]


def _solve(fn, lo, hi, target, increasing, steps=60):
    """Binary search a lever for the value that yields target ROC.

    `increasing` says which way ROC moves as the lever rises. Returns None when the
    target isn't reachable anywhere in [lo, hi] — that matters, because "no offer
    price makes this work" is a real and useful answer.
    """
    f_lo, f_hi = fn(lo), fn(hi)
    # target must sit between the endpoints, or it isn't reachable in range
    if increasing:
        if f_hi < target:
            return None
    else:
        if f_lo < target:
            return None
    for _ in range(steps):
        mid = (lo + hi) / 2
        v = fn(mid)
        if (v < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def path_to_strong(pf: ProForma, target_roc: float = 0.35) -> dict:
    """
    "What would it take to make this a STRONG buy?"

    Rather than making someone move sliders until the badge turns green, solve each
    lever independently: hold everything else at today's numbers and find the single
    value of that lever which lands exactly on the target return.

    Returns one entry per lever, each with the number needed and how far it is from
    where things stand. A lever that can't get there in a sane range returns
    reachable=False — "no realistic offer price saves this lot" is the useful answer
    in that case, not a fabricated number.

    Levers, and which way they push the return:
      offer price      — pay less, return rises        (decreasing in land)
      construction $/sf— build cheaper, return rises   (decreasing in cost)
      buildable sqft   — more house spreads the land   (usually increasing)
      exit $/sf        — sell higher, return rises     (increasing)
    """
    if pf.exit_psf_basis is None or not pf.land_cost or not pf.buildable_sqft:
        return dict(ok=False)

    cur = pf._run_one(pf.exit_psf_basis)["roc"]
    out = dict(ok=True, current_roc=cur, target_roc=target_roc,
               already=cur >= target_roc, levers=[])
    if cur >= target_roc:
        return out

    ask = float(pf.land_cost)
    cpsf = float(pf.a.construction_psf)
    bld = float(pf.buildable_sqft)
    xpsf = float(pf.exit_psf_basis)

    # 1) offer price
    v = _solve(lambda L: _roc_with(pf, land=L), 1000.0, ask * 1.5, target_roc,
               increasing=False)
    if v and v < ask:
        out["levers"].append(dict(
            key="offer", label="Pay less for the land",
            needed=round(v), unit="$", current=round(ask), reachable=True,
            phrase=(f"offer <b>${v:,.0f}</b> or less "
                    f"({(1 - v/ask)*100:.0f}% below the ${ask:,.0f} ask)")))
    else:
        best = _roc_with(pf, land=1000.0)
        out["levers"].append(dict(
            key="offer", label="Pay less for the land", reachable=False,
            phrase=(f"price alone can't do it — even at a near-zero land cost this "
                    f"tops out around {best:.0%}")))

    # 2) construction cost
    v = _solve(lambda C: _roc_with(pf, constr=C), 200.0, cpsf * 2, target_roc,
               increasing=False)
    if v and v < cpsf:
        out["levers"].append(dict(
            key="constr", label="Build it cheaper",
            needed=round(v), unit="$/sf", current=round(cpsf), reachable=True,
            phrase=(f"build at <b>${v:,.0f}/sf</b> or less "
                    f"(vs ${cpsf:,.0f} assumed)")))
    else:
        best = _roc_with(pf, constr=200.0)
        out["levers"].append(dict(
            key="constr", label="Build it cheaper", reachable=False,
            phrase=(f"construction cost alone can't do it — even at $200/sf this tops "
                    f"out around {best:.0%}")))

    # 3) buildable square footage
    v = _solve(lambda B: _roc_with(pf, build=B), bld * 0.5, bld * 3, target_roc,
               increasing=True)
    if v and v > bld:
        out["levers"].append(dict(
            key="build", label="Build bigger",
            needed=round(v), unit="sf", current=round(bld), reachable=True,
            phrase=(f"get to <b>{v:,.0f} sf</b> buildable "
                    f"(vs {bld:,.0f} assumed — check the real prior house)")))
    else:
        out["levers"].append(dict(
            key="build", label="Build bigger", reachable=False,
            phrase=("more square footage doesn't help here — at this exit price the "
                    "extra feet cost about what they earn")))

    # 4) exit price
    v = _solve(lambda X: _roc_with(pf, exit_psf=X), xpsf * 0.5, xpsf * 3, target_roc,
               increasing=True)
    if v and v > xpsf:
        out["levers"].append(dict(
            key="exit_psf", label="Sell higher",
            needed=round(v), unit="$/sf", current=round(xpsf), reachable=True,
            phrase=(f"exit at <b>${v:,.0f}/sf</b> "
                    f"({(v/xpsf - 1)*100:.0f}% above the ${xpsf:,.0f} comp basis)")))
    else:
        out["levers"].append(dict(
            key="exit_psf", label="Sell higher", reachable=False,
            phrase="not reachable on exit price alone"))

    return out


def discount_to_breakeven(pf: ProForma, target_roc: float = 0.20) -> dict:
    """
    The negotiation target, per lot. Instead of ASSUMING a discount off asking, this
    computes the discount the lot NEEDS to clear a target return — Michael's walk-away
    number before he calls the agent.

    Holds everything fixed except land cost and searches for the asking-price discount
    that yields target_roc. A negative "discount" means the lot already clears the
    target at full asking (it has room to overpay); a discount above ~25% means no
    realistic negotiation saves it.
    """
    if pf.exit_psf_basis is None or not pf.land_cost:
        return dict(ok=False)
    ask = pf.land_cost
    # binary search the land cost that yields target_roc
    lo, hi = 0.0, ask * 2  # land from free to 2x ask
    for _ in range(50):
        mid = (lo + hi) / 2
        pf2 = ProForma(pf.buildable_sqft, mid, pf.exit_psf_basis, pf.jurisdiction,
                       pf.a, pf.express)
        roc = pf2._run_one(pf.exit_psf_basis)["roc"]
        # higher land -> lower ROC, so if roc too low we need LESS land
        if roc < target_roc:
            hi = mid
        else:
            lo = mid
    breakeven_land = (lo + hi) / 2
    discount_pct = round((1 - breakeven_land / ask) * 100)
    if discount_pct <= 0:
        verdict = f"clears {target_roc:.0%} at full asking (room to overpay {abs(discount_pct)}%)"
    elif discount_pct <= 25:
        verdict = f"needs {discount_pct}% off asking to clear {target_roc:.0%}"
    else:
        verdict = f"needs {discount_pct}% off — outside a realistic negotiation"
    return dict(ok=True, discount_pct=discount_pct,
                breakeven_land=round(breakeven_land), ask=round(ask),
                target_roc=target_roc, verdict=verdict)
