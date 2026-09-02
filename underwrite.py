"""
Second-stage underwriting — the deal you actually act on.
=========================================================

The analyzer screens a market: which lots clear the bar, and by how much. That is a
sorting job, and margin over market is the right metric for it.

This is the step after. One lot, chosen. It answers the questions that decide whether
to write an offer, and that a sorting metric deliberately ignores:

    What does the investor actually receive, after the split?
    What is that as an annualised return, not just a multiple?
    Does leverage help or hurt THIS deal, at THIS breakeven?
    Which assumption, if wrong, ends it?

Kept in the app rather than as a separate workbook on purpose. Three financing
models had already drifted apart because they lived in three places; a second-stage
model in a separate file would drift from the ranking the same way, and would go
stale the moment a Certificate of Occupancy changed a square footage. This reads
the same verified record the ranking does.

The investor-facing workbook is a one-time export for whichever property wins, not
the tool used to pick it.
"""
from __future__ import annotations
from typing import Optional
from engine import Assumptions, ProForma, ula_tax


# --------------------------------------------------------------- waterfall
def waterfall(profit: float, equity: float,
              lp_capital_share: float = 0.90,
              lp_profit_share: float = 0.50,
              months: float = 22.0) -> dict:
    """
    Distribute the outcome between LP and GP.

    Structure as stated: investors put in 90% of the equity, sponsor 10%, profits
    split 50/50. There is no preferred return and no hurdle — the split applies from
    the first dollar, in both directions.

    Two things worth seeing plainly rather than buried in a spreadsheet:

    THE EFFECTIVE PROMOTE. A 50% profit share on 10% of the capital is roughly a 44%
    carry. Normal for a friends-and-family single asset; well outside what an
    institution accepts at fund stage, where 20% over a preferred return is the
    convention. If the same investors are approached for the fund later, the change
    has to be explained.

    LOSSES FOLLOW CAPITAL, NOT THE SPLIT. On a loss the LP wears 90% of it, because
    there is no downside sharing in the profit split. The GP's 50% is upside only.
    That asymmetry is the deal's real economics and it belongs in the offering.
    """
    lp_cap = equity * lp_capital_share
    gp_cap = equity * (1 - lp_capital_share)

    if profit >= 0:
        lp_profit = profit * lp_profit_share
        gp_profit = profit * (1 - lp_profit_share)
    else:
        # losses are borne pro rata to capital
        lp_profit = profit * lp_capital_share
        gp_profit = profit * (1 - lp_capital_share)

    lp_total = lp_cap + lp_profit
    gp_total = gp_cap + gp_profit
    lp_mult = (lp_total / lp_cap) if lp_cap else 0.0
    yrs = max(months / 12.0, 0.01)
    lp_irr = (lp_mult ** (1 / yrs) - 1) if lp_mult > 0 else -1.0

    # what the sponsor's 10% actually earns them, as a multiple
    gp_mult = (gp_total / gp_cap) if gp_cap else 0.0
    effective_promote = ((1 - lp_profit_share) - (1 - lp_capital_share)) / \
                        (1 - (1 - lp_capital_share)) if lp_capital_share < 1 else 0.0

    return dict(
        lp_capital=round(lp_cap), gp_capital=round(gp_cap),
        lp_profit=round(lp_profit), gp_profit=round(gp_profit),
        lp_total=round(lp_total), gp_total=round(gp_total),
        lp_multiple=lp_mult, gp_multiple=gp_mult, lp_irr=lp_irr,
        effective_promote=effective_promote,
        loss=profit < 0,
    )


# ------------------------------------------------- structure comparison
STRUCTURES = {
    "Conservative — all cash": dict(land_ltv=0.00, construction_ltc=0.00),
    "Traditional — 65% LTC":   dict(land_ltv=0.65, construction_ltc=0.65),
    "High leverage":           dict(land_ltv=0.50, construction_ltc=1.00),
}


def compare_structures(buildable_sqft: float, land_cost: float, exit_psf: float,
                       jurisdiction: str, base: Assumptions,
                       downside_psf: Optional[float] = None) -> list:
    """
    The same deal under three capital structures, upside and downside together.

    Leverage is usually presented as a single number, which is how it gets sold. The
    honest presentation is both directions on one line: the structure that turns a
    good outcome into a spectacular one turns a poor outcome into a wipeout by the
    same mechanism, and the deal has not changed.
    """
    rows = []
    for name, kw in STRUCTURES.items():
        a = Assumptions(**{**base.__dict__, **kw})
        pf = ProForma(buildable_sqft, land_cost, exit_psf, jurisdiction, a, express=False)
        up = pf._run_one(exit_psf)
        be = pf.breakeven_sale_psf()
        row = dict(name=name, equity=up["equity"], loan=up["loan"],
                   total_cost=up["total_cost"], profit=up["profit"],
                   roc=up["roc"], coc=up["coc"], breakeven=be)
        if downside_psf:
            dn = ProForma(buildable_sqft, land_cost, downside_psf, jurisdiction, a,
                          express=False)._run_one(downside_psf)
            row.update(down_profit=dn["profit"], down_coc=dn["coc"])
        rows.append(row)
    return rows


def offer_grid(buildable_sqft: float, ask: float, jurisdiction: str,
               base: Assumptions, comp_median: float,
               target_roc: float = 0.20) -> dict:
    """
    THE DECISION TABLE — what to offer.

    Replaces three separate sensitivity views (exit x construction, hold length,
    and the nine-column scenario block) with the one question actually being asked
    at the point of writing an offer:

        Given what the market might do, what can I pay?

    Rows are the offer price, which is the only variable on this list the buyer
    controls. Columns are the exit price, which is the one they control least and
    which moves the return most. The comparable median is marked, because that is
    where the market is now rather than where the deal needs it to be.

    Read it by choosing the column you actually believe, then running down to the
    first offer that clears. That number is the bid.
    """
    exits = [comp_median * m for m in (0.90, 1.0, 1.15, 1.30, 1.45)]
    discounts = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25)
    rows = []
    for d in discounts:
        offer = ask * (1 - d)
        cells = []
        for e in exits:
            pf = ProForma(buildable_sqft, offer, e, jurisdiction, base, express=False)
            r = pf._run_one(e)
            cells.append(dict(exit_psf=e, roc=r["roc"], coc=r["coc"],
                              clears=r["roc"] >= target_roc,
                              profit=r["profit"]))
        rows.append(dict(discount=d, offer=offer, cells=cells))

    # the lowest exit price at which the asking price still clears the target
    at_ask = rows[0]["cells"]
    needed_exit = next((c["exit_psf"] for c in at_ask if c["clears"]), None)
    # the offer needed if the market only delivers its own median
    at_median = [r["cells"][1] for r in rows]
    needed_discount = next((rows[i]["discount"] for i, c in enumerate(at_median)
                            if c["clears"]), None)

    return dict(exits=exits, rows=rows, comp_median=comp_median,
                target_roc=target_roc, needed_exit=needed_exit,
                needed_discount=needed_discount, ask=ask)


# ------------------------------------------------------------ sensitivity
def sensitivity_grid(buildable_sqft: float, land_cost: float, jurisdiction: str,
                     base: Assumptions,
                     exit_prices: tuple = (1250, 1400, 1550, 1700, 1900),
                     constr_costs: tuple = (700, 750, 850, 1000)) -> dict:
    """
    Return on cost across exit price and construction cost.

    These are the two variables that moved every deal we have looked at, and they
    move it in opposite directions, so a single-variable sensitivity understates the
    range. Hold length is handled separately because it is the one the sponsor has
    some influence over.
    """
    grid = []
    for c in constr_costs:
        a = Assumptions(**{**base.__dict__, "construction_psf": float(c)})
        row = {"construction_psf": c, "cells": []}
        for p in exit_prices:
            pf = ProForma(buildable_sqft, land_cost, p, jurisdiction, a, express=False)
            row["cells"].append(dict(exit_psf=p, roc=pf._run_one(p)["roc"]))
        grid.append(row)
    return dict(exit_prices=exit_prices, rows=grid)


def hold_sensitivity(buildable_sqft: float, land_cost: float, exit_psf: float,
                     jurisdiction: str, base: Assumptions,
                     months_options: tuple = (14, 18, 24, 30, 36)) -> list:
    """
    What a longer build costs.

    Two Palisades builds pulled from LADBS ran 34 and 35 months against a 14-18 month
    assumption. This is not a tail scenario; it is what the record shows.
    """
    out = []
    for m in months_options:
        a = Assumptions(**{**base.__dict__, "build_months": float(m)})
        r = ProForma(buildable_sqft, land_cost, exit_psf, jurisdiction, a,
                     express=False)._run_one(exit_psf)
        out.append(dict(build_months=m, total_cost=r["total_cost"],
                        interest=r["interest"], profit=r["profit"],
                        roc=r["roc"], coc=r["coc"]))
    return out


# ------------------------------------------------------- what breaks it
def what_breaks_it(buildable_sqft: float, land_cost: float, exit_psf: float,
                   jurisdiction: str, base: Assumptions) -> list:
    """
    Which single assumption, moved to a plausible worse value, does the most damage.

    Ranked by effect. The point is to identify what actually has to be true, so
    diligence money goes to the right question instead of the interesting one.
    """
    def roc(a: Assumptions, psf: float, sqft: float = None, land: float = None) -> float:
        return ProForma(sqft or buildable_sqft, land or land_cost, psf,
                        jurisdiction, a, express=False)._run_one(psf)["roc"]

    baseline = roc(base, exit_psf)
    tests = []

    # exit price falls to the comparable median
    tests.append(("Exit price 15% lower",
                  roc(base, exit_psf * 0.85),
                  "The comps do not support the assumed exit. This is the variable "
                  "we control least and it moves the return most."))

    # construction over-runs
    a2 = Assumptions(**{**base.__dict__,
                        "construction_psf": base.construction_psf * 1.20})
    tests.append(("Construction 20% over", roc(a2, exit_psf),
                  "A conversation becomes a bid, and the bid is higher. Fixed-price "
                  "or GMP contracting transfers this risk."))

    # buildable area smaller than believed
    tests.append(("Buildable area 15% smaller",
                  roc(base, exit_psf, sqft=buildable_sqft * 0.85),
                  "The prior square footage, or the zoning envelope, is smaller than "
                  "assumed. Settled by the Certificate of Occupancy."))

    # schedule slips to what the record shows
    a4 = Assumptions(**{**base.__dict__, "build_months": 30.0})
    tests.append(("Build takes 30 months", roc(a4, exit_psf),
                  "Two comparable Palisades builds took 34 and 35 months."))

    # rate moves
    a5 = Assumptions(**{**base.__dict__, "loan_rate": base.loan_rate + 0.02})
    tests.append(("Loan rate 200bp higher", roc(a5, exit_psf),
                  "Confirmed by term sheet, not assumed."))

    out = [dict(factor=f, roc=r, delta=r - baseline, note=n) for f, r, n in tests]
    return sorted(out, key=lambda x: x["delta"])
