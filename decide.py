"""
The decision layer.
===================

Everything above this module answers "which lots rank highest." This module answers
the question actually being asked, which is "should we commit real money to this
specific parcel, and if we can't decide yet, what is the cheapest thing that would
let us."

Four calculations, in the order they change behaviour:

    resolution_value()   what to go check, ranked by how much it moves the answer
                         divided by what it costs to find out
    rank_stability()     how often each lot wins across the plausible input space,
                         and where the crossovers sit
    required_case()      the downside an LP's analyst will build in ten minutes,
                         computed here so it is already on the page
    option_economics()   what the verification period is worth, which is the
                         structural way to make the decision smaller

The premise underneath all four: the ranking has already inverted once on new
evidence, and every unverified figure checked so far moved against us. A tool that
presents a sort order implies a confidence the inputs do not support. These functions
replace the sort order with a decision.
"""
from __future__ import annotations
import math
import random
from dataclasses import replace
from typing import Optional

from engine import Assumptions, ProForma


# =============================================================== cost of knowing
# What it actually takes to resolve each uncertain input. The weights are ordinal,
# not monetary — they exist to rank actions against each other, and the ordering is
# the part that matters. A ZIMAS check and a GMP bid are not two points on the same
# scale in any meaningful sense; they are different kinds of thing.
COST = {
    "free":      dict(weight=1.0,  label="free · minutes",
                      note="An online lookup. No permission, no cost, no waiting."),
    "cheap":     dict(weight=4.0,  label="free · days",
                      note="A records request or one phone call. Free, but it queues."),
    "moderate":  dict(weight=12.0, label="paid · a week or two",
                      note="Costs money or a professional's time. Schedulable."),
    "expensive": dict(weight=40.0, label="paid · weeks, and a relationship",
                      note="A bid, a site visit, or a counterparty who has to agree."),
    # Not actions. Shown because the swing matters, ranked last because there is
    # nothing to go and do about them.
    "bounded":      dict(weight=1e9, label="already bounded",
                         note="The range is known from the record. Nothing to resolve."),
    "unresolvable": dict(weight=1e9, label="cannot be resolved in advance",
                         note="No amount of diligence settles it. Handle it in the structure."),
}


# ======================================================= 1 · what to check next
def _margin_at(pf: ProForma, basis: float, *, buildable=None, constr=None,
               months=None) -> Optional[float]:
    """
    Margin over market with one input moved and everything else held. Rebuilds the
    pro forma rather than mutating it, so a sweep can never leak state into the row
    the user is looking at.
    """
    if not basis:
        return None
    a = pf.a
    if constr is not None or months is not None:
        a = replace(a,
                    construction_psf=(constr if constr is not None else a.construction_psf),
                    build_months=(months if months is not None else a.build_months))
    probe = ProForma(
        buildable_sqft=(buildable if buildable is not None else pf.buildable_sqft),
        land_cost=pf.land_cost, exit_psf_basis=pf.exit_psf_basis,
        jurisdiction=pf.jurisdiction, a=a, express=pf.express,
        comp_low=pf.comp_low, comp_high=pf.comp_high)
    be = probe.breakeven_sale_psf()
    return (be / basis - 1) if be else None


def resolution_value(pf: ProForma, facts: dict, verified: bool,
                     basis: Optional[float]) -> list:
    """
    Rank the open questions on this lot by how much the answer moves per unit of
    effort to find out.

    This is the single highest-leverage output in the tool, because most of the time
    the honest answer is not "buy it" or "pass" but "you cannot decide yet, and here
    is the twenty-minute check that would let you." Sorting by swing alone would put
    the construction bid first every time; dividing by cost surfaces the two free
    lookups that move more than the bid does.

    Returns a list of dicts, best action first. Each carries the swing in margin
    points, what it costs, and the literal next step.
    """
    if not basis or not pf.buildable_sqft:
        return []
    out = []

    def add(name, lo, hi, cost, action, why):
        if lo is None or hi is None:
            return
        swing = abs(hi - lo)
        if swing < 0.005:                    # under half a margin point: not worth a trip
            return
        out.append(dict(
            name=name, swing=swing, lo=min(lo, hi), hi=max(lo, hi),
            cost=cost, cost_label=COST[cost]["label"], cost_note=COST[cost]["note"],
            value=swing / COST[cost]["weight"], action=action, why=why))

    # --- prior square footage -------------------------------------------------
    # Five of five checked against LADBS were wrong and every one was overstated,
    # by a mean of about 27%. Until a certificate exists, the envelope is a claim.
    if not verified:
        claimed = pf.buildable_sqft
        add("Prior square footage",
            _margin_at(pf, basis, buildable=claimed),
            _margin_at(pf, basis, buildable=claimed * 0.73),
            "free",
            "Pull the Certificate of Occupancy: lacitydbs.org, search the address, "
            "Certificate of Occupancy, save the PDF, drop it in Verified records.",
            "Every prior-square-footage figure checked against LADBS so far was "
            "wrong and overstated, on average by about 27%. The whole envelope, and "
            "therefore every number below it, scales off this one input.")

    # --- rebuild path ---------------------------------------------------------
    # EO8 bypasses local Coastal Act review and is bounded by LAMC zoning rather
    # than the prior structure. Whether that route is open is a Coastal Zone
    # question, and on a lot where something small burned it is the difference
    # between a single storey and a full zoning envelope.
    env = facts.get("envelope") or {}
    eo1 = env.get("eo1_sqft") or env.get("eo1")
    eo8 = env.get("eo8_sqft") or env.get("eo8")
    if eo1 and eo8 and abs(eo8 - eo1) > 1:
        add("Rebuild path (EO1 vs EO8)",
            _margin_at(pf, basis, buildable=max(eo1, eo8)),
            _margin_at(pf, basis, buildable=min(eo1, eo8)),
            "free",
            "Check the parcel on ZIMAS for Coastal Zone status and dual-permit "
            "jurisdiction. If it is outside, the EO8 envelope stands.",
            "EO8 permits a zoning-compliant rebuild bounded by LAMC rather than by "
            "what burned, and bypasses local Coastal Act and CEQA review. Whether "
            "that route is available is a Coastal Zone question and it is free to "
            "answer.")

    # --- construction cost ----------------------------------------------------
    # Terrain drives it: ~$700/sf on the Alphabet flats, ~$1,150 hillside. Where the
    # street is not recognised, the band itself is the open question, and that is a
    # much larger swing than the +/- around a known band.
    band = facts.get("area_band") or facts.get("area_flag")
    cur = pf.a.construction_psf
    if band in (None, "unknown", "default"):
        add("Construction cost band (terrain unconfirmed)",
            _margin_at(pf, basis, constr=700.0),
            _margin_at(pf, basis, constr=1150.0),
            "moderate",
            "Confirm terrain and access. A site visit settles the band; an "
            "engineer's brief settles the number.",
            "The street is not recognised as either flats or hillside, so the cost "
            "band is unresolved. Flats run about $700/sf and hillside about $1,150 "
            "for caissons, shoring and access.")
    else:
        add("Construction cost (no bid yet)",
            _margin_at(pf, basis, constr=cur * 0.90),
            _margin_at(pf, basis, constr=cur * 1.20),
            "expensive",
            "Get a written fixed-price or GMP bid. Note the builder is a partner in "
            "the transaction, so this pricing is not arm's length and must be "
            "disclosed.",
            "The band is a default, not a quote. Construction and exit price do "
            "roughly five times the damage of anything else in the model.")

    # --- schedule -------------------------------------------------------------
    # Two comparable Palisades builds from LADBS inspection records: 501 Swarthmore
    # 34 months, 16815 Livorno 35. The range is narrow, so this is usually a small
    # swing — which is itself worth showing, because it stops the argument.
    add("Build schedule",
        _margin_at(pf, basis, months=30.0),
        _margin_at(pf, basis, months=35.0),
        "bounded",
        "Nothing to do. Both comparable Palisades builds are already in the record: "
        "501 Swarthmore 34 months, 16815 Livorno 35. Hold the schedule at 30 to 35 "
        "and stop arguing about it.",
        "Bounded by observed builds rather than estimated, so this is a known "
        "range rather than an open question.")

    # --- exit price -----------------------------------------------------------
    # The binding constraint, and the one thing no amount of diligence resolves.
    # It appears here so it is visible, flagged as unresolvable rather than
    # expensive, because the right response is structural, not investigative.
    comps = facts.get("comps") or []
    psfs = sorted(c["psf"] for c in comps if c.get("psf"))
    if len(psfs) >= 3:
        p25, p75 = _pct(psfs, 0.25), _pct(psfs, 0.75)
        be = pf.breakeven_sale_psf()
        if be:
            out.append(dict(
                name="Exit price", swing=abs(be / p25 - be / p75),
                lo=be / p75 - 1, hi=be / p25 - 1,
                cost="unresolvable",
                cost_label=COST["unresolvable"]["label"],
                cost_note=COST["unresolvable"]["note"],
                value=0.0,
                action="Do not try to resolve this. Price the downside case at the "
                       "25th percentile of the matched comps and check the deal "
                       "still survives.",
                why=f"The matched comps run ${min(psfs):,} to ${max(psfs):,}/sf. "
                    f"This is the binding constraint and it is not an information "
                    f"problem, so it belongs in the structure rather than in the "
                    f"diligence list."))

    out.sort(key=lambda d: d["value"], reverse=True)
    return out


def _pct(sorted_vals: list, q: float) -> float:
    """Linear-interpolated percentile. Small n here, so no numpy dependency."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    i = q * (len(sorted_vals) - 1)
    lo, frac = int(math.floor(i)), i - math.floor(i)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo]))


# ================================================== 2 · how stable is the rank
def rank_stability(lots: list, draws: int = 1500, seed: int = 20260902) -> dict:
    """
    Sweep every lot across the plausible input space simultaneously and count how
    often each finishes on top.

    "Marquette is first" is a sort order. "Marquette is top-three in 78% of
    plausible worlds, and the crossover with Oreo happens when construction passes
    $840/sf" is a decision. The ranking here has already inverted once on new
    evidence, so a headline position with no stability attached overstates what the
    inputs support.

    Seeded deliberately: the figure must not move when a user clicks an unrelated
    widget and Streamlit re-runs the script.

    `lots` is a list of dicts with keys: name, pf, basis, verified, comps.
    """
    usable = [l for l in lots if l.get("pf") and l.get("basis")]
    if len(usable) < 2:
        return dict(ok=False, note="Rank stability needs at least two priceable lots.")

    rng = random.Random(seed)
    wins = {l["name"]: 0 for l in usable}
    top3 = {l["name"]: 0 for l in usable}
    margins = {l["name"]: [] for l in usable}

    for _ in range(draws):
        scored = []
        for l in usable:
            pf, basis = l["pf"], l["basis"]
            # exit basis: resample from the lot's own matched comps rather than a
            # symmetric band around the median, because the distribution is not
            # symmetric and inventing one would be worse than using six real points
            psfs = [c["psf"] for c in (l.get("comps") or []) if c.get("psf")]
            b = rng.choice(psfs) if psfs else basis
            # buildable: unverified lots carry the observed overstatement, which is
            # one-sided. Verified lots get a small measurement tolerance only.
            if l.get("verified"):
                bu = pf.buildable_sqft * rng.uniform(0.98, 1.02)
            else:
                bu = pf.buildable_sqft * rng.uniform(0.70, 1.00)
            # construction: around the band in use
            cs = pf.a.construction_psf * rng.uniform(0.90, 1.20)
            # schedule: bounded by the two observed Palisades builds
            mo = rng.uniform(30.0, 35.0)
            m = _margin_at(pf, b, buildable=bu, constr=cs, months=mo)
            if m is not None:
                scored.append((m, l["name"]))
        if not scored:
            continue
        scored.sort()                          # lower margin over market is better
        wins[scored[0][1]] += 1
        for _, n in scored[:3]:
            top3[n] += 1
        for m, n in scored:
            margins[n].append(m)

    n = max(1, draws)
    rows = []
    for l in usable:
        nm = l["name"]
        ms = sorted(margins[nm])
        rows.append(dict(
            name=nm,
            p_first=wins[nm] / n,
            p_top3=top3[nm] / n,
            margin_p10=_pct(ms, 0.10) if ms else None,
            margin_p50=_pct(ms, 0.50) if ms else None,
            margin_p90=_pct(ms, 0.90) if ms else None))
    rows.sort(key=lambda r: r["p_first"], reverse=True)
    # crossover between the top two BY RESULT, not by input order
    order = {r["name"]: i for i, r in enumerate(rows)}
    ranked = sorted(usable, key=lambda l: order.get(l["name"], 999))
    return dict(ok=True, draws=draws, rows=rows,
                crossover=_crossover(ranked[:2]) if len(ranked) >= 2 else None)


def _crossover(pair: list) -> Optional[dict]:
    """
    The construction cost at which the top two lots swap places. Stated as a single
    number because that is what someone can hold in their head walking into a
    contractor meeting.
    """
    a, b = pair[0], pair[1]
    if not (a.get("pf") and b.get("pf") and a.get("basis") and b.get("basis")):
        return None

    def gap(c):
        ma = _margin_at(a["pf"], a["basis"], constr=c)
        mb = _margin_at(b["pf"], b["basis"], constr=c)
        return None if (ma is None or mb is None) else ma - mb

    lo, hi = 500.0, 1500.0
    g_lo, g_hi = gap(lo), gap(hi)
    if g_lo is None or g_hi is None or (g_lo > 0) == (g_hi > 0):
        return dict(exists=False, a=a["name"], b=b["name"],
                    note=(f"{a['name']} stays ahead of {b['name']} across the whole "
                          f"$500 to $1,500/sf construction range. The ordering is not "
                          f"a cost question."))
    for _ in range(50):
        mid = (lo + hi) / 2
        g = gap(mid)
        if g is None:
            break
        if (g > 0) == (g_lo > 0):
            lo, g_lo = mid, g
        else:
            hi = mid
    return dict(exists=True, a=a["name"], b=b["name"], psf=round((lo + hi) / 2),
                note=(f"{a['name']} and {b['name']} swap at about "
                      f"${round((lo + hi) / 2):,}/sf construction."))


# ================================================= 3 · the case you must show
def required_case(pf: ProForma, facts: dict, verified: bool) -> dict:
    """
    The downside an LP's analyst builds in the first ten minutes. It is computed
    here, always, and shown beside the base case rather than hidden behind a slider,
    because a model whose lowest case is the market median has no downside in it at
    all.

    Three moves, none of them pessimistic, all of them defensible:
      exit at the 25th percentile of the matched comps, not the weighted median
      construction at the hillside band wherever terrain is unconfirmed
      schedule at 35 months, the longer of the two observed Palisades builds

    Unverified square footage takes the observed overstatement as well, because
    five out of five is a pattern rather than a possibility.
    """
    comps = facts.get("comps") or []
    psfs = sorted(c["psf"] for c in comps if c.get("psf"))
    exit_p25 = _pct(psfs, 0.25) if len(psfs) >= 3 else (pf.comp_low or pf.exit_psf_basis)

    band = facts.get("area_band") or facts.get("area_flag")
    constr = 1150.0 if band in (None, "unknown", "default") else pf.a.construction_psf

    buildable = pf.buildable_sqft * (1.0 if verified else 0.73)

    a = replace(pf.a, construction_psf=constr, build_months=35.0)
    probe = ProForma(buildable_sqft=buildable, land_cost=pf.land_cost,
                     exit_psf_basis=exit_p25, jurisdiction=pf.jurisdiction, a=a,
                     express=pf.express, comp_low=pf.comp_low, comp_high=pf.comp_high)
    r = probe._run_one(exit_p25)
    be = probe.breakeven_sale_psf()
    return dict(
        ok=True, exit_psf=round(exit_p25 or 0), construction_psf=round(constr),
        months=35.0, buildable=round(buildable),
        breakeven_psf=round(be) if be else None,
        margin=(be / exit_p25 - 1) if (be and exit_p25) else None,
        profit=r["profit"], equity=r["equity"], roc=r["roc"],
        moves=[
            f"Exit at the 25th percentile of the matched comps (${round(exit_p25):,}/sf) "
            f"rather than the weighted median.",
            (f"Construction at the hillside band (${round(constr):,}/sf) because the "
             f"terrain is unconfirmed." if band in (None, "unknown", "default")
             else f"Construction held at the area band (${round(constr):,}/sf)."),
            "Schedule at 35 months, the longer of 501 Swarthmore (34) and 16815 "
            "Livorno (35).",
            (f"Buildable cut 27% to {round(buildable):,} sf, the mean overstatement "
             f"across five LADBS checks." if not verified
             else "Buildable held: the square footage is certified."),
        ])


# ============================================ 4 · make the decision smaller
def option_economics(pf: ProForma, actions: list, land_cost: float) -> dict:
    """
    The structural answer, and the one that beats every improvement to the model.

    The difficulty here does not come from the model being imprecise. It comes from
    being asked to commit irreversibly on inputs that are not yet verified. A
    feasibility contingency converts an unverified lot into a verified one before
    the money is at risk: tie it up, do the free checks inside the option period,
    and walk if the certificate comes back short.

    What this computes is the ceiling on what that period is rationally worth, and
    how long it has to be to cover the open items. It does not draft anything.
    Contract terms, deposit structure and remedies are COUNSEL.
    """
    resolvable = [a for a in actions if a["cost"] not in ("unresolvable", "bounded")]
    if not resolvable:
        return dict(ok=False, note="Nothing left to resolve on this lot.")

    base = ((pf.breakeven_sale_psf() / pf.exit_psf_basis - 1)
            if pf.exit_psf_basis else 0.0)
    worst = max((a["hi"] for a in resolvable), default=base)
    swing = max(0.0, worst - base)
    # Dollars, not a percentage: what the equity is exposed to if the unverified
    # inputs resolve the way the last five did.
    at_risk = round(pf.buildable_sqft * (pf.exit_psf_basis or 0) * swing)

    days = {"free": 7, "cheap": 21, "moderate": 30, "expensive": 60}
    driver = max(resolvable, key=lambda a: days[a["cost"]])
    free_only = [a for a in resolvable if a["cost"] == "free"]

    return dict(
        ok=True,
        period_days=days[driver["cost"]],
        free_period_days=7 if free_only else None,
        driver=driver["name"],
        swing_pct=swing,
        at_risk=at_risk,
        free_actions=[a["name"] for a in free_only],
        note=(f"A {days[driver['cost']]}-day feasibility period covers every "
              f"resolvable item here, the binding one being "
              f"{driver['name'].lower()}. "
              + (f"The free checks ({', '.join(a['name'].lower() for a in free_only)}) "
                 f"close inside a week on their own. " if free_only else "")
              + f"If the unverified inputs resolve the way the last five did, about "
                f"${at_risk:,} of value moves against you, which is what the period "
                f"buys the right to walk away from."),
        no_fee_estimate=(
            "No maximum fee is quoted. Converting the exposure into a rational "
            "deposit needs a probability that the inputs resolve badly, and there "
            "is no published base rate for that. Estimating one would be inventing "
            "the number the whole structure exists to avoid needing."),
        counsel="COUNSEL — contingency language, deposit structure, remedies and "
                "whether the deposit goes hard are all counsel items. This is the "
                "economic ceiling on the fee, not a term sheet.")
