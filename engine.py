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

# Bumped on every substantive change and rendered in the app footer, so anyone
# looking at the deployed tool can tell which build it is without trusting a commit
# log that reads "Add files via upload" twenty times over.
BUILD = "2026-09-02b · ULA indexed · cliff callsite · sample-path crashes · guide in-app"
import math
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ------------------------------------------------------------------ assumptions
# ULA thresholds as certified for transactions closing after 30 June 2026. They index
# to Chained CPI every 1 July, so a 2028-29 exit does not face these numbers.
ULA_BASE_YEAR = 2026
ULA_BASE_T1 = 5_400_000.0
ULA_BASE_T2 = 10_900_000.0
ULA_RATE_1 = 0.040
ULA_RATE_2 = 0.055
ULA_INDEX_DEFAULT = 0.025          # Chained CPI, exposed as an assumption


def ula_thresholds(exit_year: int = ULA_BASE_YEAR,
                   index_rate: float = ULA_INDEX_DEFAULT) -> tuple:
    """
    The ULA tiers that will actually apply at exit, not the ones in force today.

    The thresholds index to Chained CPI each 1 July. Hardcoding the 2026 figures
    understates them for a 2028-29 sale by roughly 6%, which pushes both the cliff
    and the dead zone below where they will really sit and overstates the tax drag
    on exactly the sale prices this fund is underwriting.

        2026   $5,400,000   $10,900,000
        2029   $5,815,000   $11,738,000   (at 2.5%)

    Indexing is applied from the base year forward and never backward — a sale this
    year faces this year's numbers.
    """
    n = max(0, int(exit_year) - ULA_BASE_YEAR)
    f = (1 + index_rate) ** n
    return ULA_BASE_T1 * f, ULA_BASE_T2 * f


def ula_tax(sale_price: float, enabled: bool = True,
            exit_year: int = ULA_BASE_YEAR,
            index_rate: float = ULA_INDEX_DEFAULT) -> dict:
    """
    Measure ULA — the LA transfer tax, and not a small line.

    RATES (thresholds indexed to the exit year, see ula_thresholds):
        below tier 1              0%
        tier 1 to tier 2          4.0%
        tier 2 and above          5.5%

    Two things people get wrong, both of which matter here:

    1. IT APPLIES TO THE ENTIRE SALE PRICE, not just the slice above the threshold.
       A sale at the tier-1 threshold owes 4% of everything; a dollar below owes
       nothing. That is a cliff, not a ramp, and it is worth real money on exits
       landing near a line.

    2. It sits on top of the existing documentary transfer taxes — 0.45% City plus
       0.11% County = 0.56% — which apply at any price.

    Seller pays at closing, on gross price, not on gain.

    ON REPEAL — CORRECTED 2 SEPTEMBER 2026. Earlier versions of this model noted the
    Local Taxpayer Protection Act as certified for the November 2026 ballot and
    treated repeal as a live possibility. That is no longer true. The measure was
    WITHDRAWN on 25 June 2026, before qualifying, under a deal between its
    proponents, the Governor and legislative leaders. It was replaced by ACA 22
    (Proposition 43), which concerns voter-approval thresholds for local special
    taxes and does NOT limit real estate transfer taxes. The provisions that might
    have reached ULA were removed from consideration.

    So ULA should be underwritten as permanent. The toggle remains for sensitivity
    testing, but turning it off is no longer modelling a plausible outcome.
    """
    t1, t2 = ula_thresholds(exit_year, index_rate)
    if not sale_price or sale_price <= 0:
        return dict(rate=0.0, tax=0.0, tier="none", doc_tax=0.0, total=0.0,
                    near_cliff=False, t1=t1, t2=t2)
    doc = sale_price * 0.0056
    if not enabled:
        return dict(rate=0.0, tax=0.0, tier="ULA off", doc_tax=doc, total=doc,
                    near_cliff=False, t1=t1, t2=t2)
    if sale_price >= t2:
        rate, tier = ULA_RATE_2, f"5.5% (over ${t2:,.0f})"
    elif sale_price >= t1:
        rate, tier = ULA_RATE_1, f"4% (${t1:,.0f}-${t2:,.0f})"
    else:
        rate, tier = 0.0, f"under ${t1:,.0f} — exempt"
    tax = sale_price * rate
    near = any(t <= sale_price <= t * (1 + r + 0.005)
               for t, r in ((t1, ULA_RATE_1), (t2, ULA_RATE_2)))
    return dict(rate=rate, tax=round(tax), tier=tier, doc_tax=round(doc),
                total=round(tax + doc), near_cliff=near, t1=t1, t2=t2)


def cliff_advice(sale_price: float, exit_year: int = ULA_BASE_YEAR,
                 index_rate: float = ULA_INDEX_DEFAULT):
    """
    Where an exit lands just above a threshold, selling for LESS nets MORE, because
    the tax hits the whole price rather than the excess. Free money, easy to miss.
    """
    t1, t2 = ula_thresholds(exit_year, index_rate)
    for thresh, rate in ((t1, ULA_RATE_1), (t2, ULA_RATE_2)):
        if thresh <= sale_price <= thresh * (1 + rate + 0.005):
            below = thresh - 1_000
            net_at = sale_price - sale_price * rate
            net_below = below - (below * ULA_RATE_2 if below >= t2 else
                                 below * ULA_RATE_1 if below >= t1 else 0)
            if net_below > net_at:
                gain = net_below - net_at
                return (f"<b>ULA threshold cliff.</b> At ${sale_price:,.0f} the tax is "
                        f"{rate:.1%} of the <i>whole</i> price "
                        f"(${sale_price*rate:,.0f}). Pricing at ${below:,.0f} instead "
                        f"nets about <b>${gain:,.0f} more</b>. The tax is a cliff, not "
                        f"a ramp — worth designing the exit around."
                        f"<br><span class='cite'>Threshold shown is the "
                        f"{exit_year} figure, indexed from the 2026 base.</span>")
    return None


@dataclass
class Assumptions:
    """
    The fixed, versioned yardstick. Change one and everything re-scores together,
    so a lot scored today stays comparable to one scored last week. The version
    string stamps every output.
    """
    """
    ONE CAPITAL STACK, RECONCILED (v2.0).

    Three different financing models had been in play at once: Michael's sheet (65%
    LTC construction loan at 10.5%), this engine's original simplified carry (3%/yr
    on land plus half the draw), and a high-leverage structure (50% down on the land,
    construction fully financed, interest as a capitalised reserve, only taxes and
    insurance out of pocket). They differed by $200-325k on the same lot, which is
    enough to move a decision.

    This is now a single model with the capital structure exposed as parameters, so
    all three are expressible and comparable rather than being separate arithmetic.
    """
    # ---- build cost ----
    construction_psf: float = 750.0       # Alphabet flats; hillside runs ~1,150
    ae_pct: float = 0.05                  # architecture and engineering, % of hard cost
    contingency_pct: float = 0.08         # a spec build with no contingency isn't a pro forma

    # ---- capital structure ----
    # High-leverage structure is the default: half the land down, construction fully
    # financed by the lender, interest capitalised rather than paid monthly. It
    # minimises cash in and maximises cash-on-cash, and it magnifies the downside by
    # the same factor — both are shown wherever it is used.
    land_ltv: float = 0.50                # lender's advance against the land
    construction_ltc: float = 1.00        # lender's advance against build costs
    loan_rate: float = 0.105              # construction loan rate
    avg_utilisation: float = 0.55         # average drawn balance across the build
    capitalise_interest: bool = True      # interest reserve inside the loan

    # ---- schedule ----
    # Two Palisades builds pulled from LADBS ran 34 and 35 months. Tal's own estimate
    # was 12-18. 18 is the base; the sensitivity is exposed rather than buried.
    build_months: float = 18.0
    sale_months: float = 4.0
    taxes_insurance_annual: float = 32_500.0   # the genuine out-of-pocket carry

    # ---- exit ----
    selling_cost_pct: float = 0.05        # broker + closing
    appreciation_pct: float = 0.03        # forward escalation; observed drift ~1.5%
    new_build_premium: float = 0.10       # measured at 19-26% size-controlled

    # THE SCARCITY BET — deliberately zero in the base case. The 2028-29
    # supply-constraint thesis may prove right, but Palisades pricing through
    # mid-2026 is roughly flat, so it is a forecast rather than an observation and
    # it stays labelled as a bet wherever it appears.
    scarcity_premium: float = 0.00

    # Measure ULA. On by default. The repeal path closed on 25 June 2026 when the
    # Local Taxpayer Protection Act was withdrawn before qualifying, so this is not
    # a coin flip any more — it is the law we will exit under.
    apply_ula: bool = True
    exit_year: int = 2028              # thresholds index to Chained CPI each 1 July
    ula_index_rate: float = 0.025

    version: str = "v2.0"

    # ---- legacy shims, so older call sites keep working ----
    carrying_rate: float = 0.03
    hold_years_express: float = 1.5
    hold_years_standard: float = 3.0

    @property
    def total_months(self) -> float:
        return self.build_months + self.sale_months

    def stamp(self) -> str:
        s = (f"{self.version} · ${self.construction_psf:,.0f}/sf · A&E {self.ae_pct:.0%} · "
             f"cont {self.contingency_pct:.0%} · {self.land_ltv:.0%} land LTV / "
             f"{self.construction_ltc:.0%} constr LTC @ {self.loan_rate:.1%} · "
             f"{self.build_months:.0f}+{self.sale_months:.0f}mo · "
             f"sell {self.selling_cost_pct:.0%} · appr {self.appreciation_pct:.0%} · "
             f"premium {self.new_build_premium:.0%}"
             f"{' · ULA on (' + str(self.exit_year) + ' tiers)' if self.apply_ula else ' · ULA OFF'}")
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
        """
        One capital stack, computed the way the deal is actually financed.

        COSTS
          land + hard construction + A&E + contingency        = project costs
          lender advances land_ltv on the land and
          construction_ltc on the build costs                 = loan principal
          interest accrues on the land advance for the whole
          term and on the build advance at average utilisation
          (capitalised as a reserve, not paid monthly)
          taxes and insurance are the genuine cash carry

        EQUITY is what actually leaves the bank account: the portion of project
        costs the loan does not fund, plus the cash carry. Under the default
        structure that is half the land plus taxes and insurance — which is the
        point of the structure.
        """
        a = self.a
        months = a.total_months
        yrs = months / 12.0

        hard = self.buildable_sqft * a.construction_psf
        ae = hard * a.ae_pct
        contingency = hard * a.contingency_pct
        build_costs = hard + ae + contingency
        project_costs = self.land_cost + build_costs

        land_loan = self.land_cost * a.land_ltv
        build_loan = build_costs * a.construction_ltc
        loan_principal = land_loan + build_loan

        # land is drawn day one and carries the full term; build draws ramp
        interest = (land_loan * a.loan_rate * yrs
                    + build_loan * a.loan_rate * (a.build_months / 12.0)
                      * a.avg_utilisation
                    + build_loan * a.loan_rate * (a.sale_months / 12.0))
        cash_carry = a.taxes_insurance_annual * yrs

        total_cost = project_costs + interest + cash_carry
        equity = (project_costs - loan_principal) + cash_carry
        if not a.capitalise_interest:
            equity += interest

        # exit: comp basis escalated forward, plus the measured new-build premium
        escalated = exit_psf * ((1 + a.appreciation_pct) ** yrs)
        premium_measured = escalated * (1 + a.new_build_premium)
        # the scarcity bet applies LAST and is tracked separately so the measured
        # part of the exit price stays recoverable
        premium = premium_measured * (1 + a.scarcity_premium)
        gross_sale = premium * self.buildable_sqft

        _ula = ula_tax(gross_sale, enabled=a.apply_ula,
                       exit_year=getattr(a, "exit_year", 2026),
                       index_rate=getattr(a, "ula_index_rate", 0.025))
        selling = gross_sale * a.selling_cost_pct
        net_sale = gross_sale - selling - _ula["total"]
        profit = net_sale - total_cost

        return dict(
            exit_psf=round(exit_psf), effective_psf=round(premium),
            effective_psf_measured=round(premium_measured),
            scarcity_applied=a.scarcity_premium,
            construction=round(hard), ae=round(ae), contingency=round(contingency),
            project_costs=round(project_costs),
            loan=round(loan_principal), land_loan=round(land_loan),
            build_loan=round(build_loan),
            interest=round(interest), carry=round(cash_carry),
            total_cost=round(total_cost), equity=round(equity),
            gross_sale=round(gross_sale), selling=round(selling),
            net_sale=round(net_sale),
            ula_tax=_ula["tax"], ula_tier=_ula["tier"], doc_tax=_ula["doc_tax"],
            ula_total=_ula["total"], near_cliff=_ula["near_cliff"],
            profit=round(profit),
            roc=(profit / total_cost if total_cost else 0),
            coc=(profit / equity if equity else 0),
            hold=yrs, months=months,
        )

    def breakeven_sale_psf(self) -> float:
        """
        The actual sale price per square foot at which this deal returns exactly zero.

        This is deliberately NOT the comp basis. _run_one takes today's comp basis
        and escalates it forward by the appreciation assumption and the new-build
        premium before selling — so "exit price" was being used for two different
        things: today's market, and the 2028 sale.

        Margin over market compares this figure against TODAY's comparable median.
        That framing is the conservative one: it states plainly how far the market
        has to move from where it is now, rather than quietly assuming the move and
        then reporting the result as if it were margin.
        """
        a = self.a
        months = a.total_months
        yrs = months / 12.0
        hard = self.buildable_sqft * a.construction_psf
        build_costs = hard * (1 + a.ae_pct + a.contingency_pct)
        project_costs = self.land_cost + build_costs
        land_loan = self.land_cost * a.land_ltv
        build_loan = build_costs * a.construction_ltc
        interest = (land_loan * a.loan_rate * yrs
                    + build_loan * a.loan_rate * (a.build_months / 12.0) * a.avg_utilisation
                    + build_loan * a.loan_rate * (a.sale_months / 12.0))
        total_cost = project_costs + interest + a.taxes_insurance_annual * yrs

        # solve gross_sale where gross - selling - transfer taxes = total_cost
        lo, hi = 0.0, total_cost * 4
        for _ in range(60):
            g = (lo + hi) / 2
            net = (g - g * a.selling_cost_pct
                   - ula_tax(g, enabled=a.apply_ula,
                             exit_year=getattr(a, "exit_year", 2026),
                             index_rate=getattr(a, "ula_index_rate", 0.025))["total"])
            if net < total_cost:
                lo = g
            else:
                hi = g
        return ((lo + hi) / 2) / self.buildable_sqft if self.buildable_sqft else 0.0

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
