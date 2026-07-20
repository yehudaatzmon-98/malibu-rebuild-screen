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
    hold_years_express: float = 1.5       # like-for-like / express permit
    hold_years_standard: float = 3.0      # CDP / standard track
    version: str = "v1.0"

    def stamp(self) -> str:
        return (f"{self.version} · ${self.construction_psf:,.0f}/sf · "
                f"cont {self.contingency_pct:.0%} · carry {self.carrying_rate:.0%} · "
                f"sell {self.selling_cost_pct:.0%} · appr {self.appreciation_pct:.0%} · "
                f"premium {self.new_build_premium:.0%}")


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
        gross_sale = premium * self.buildable_sqft
        net_sale = gross_sale * (1 - self.a.selling_cost_pct)
        profit = net_sale - total_cost
        roc = profit / total_cost if total_cost else 0
        return dict(
            exit_psf=round(exit_psf), effective_psf=round(premium),
            construction=round(construction), contingency=round(contingency),
            carry=round(carry), total_cost=round(total_cost),
            gross_sale=round(gross_sale), net_sale=round(net_sale),
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
