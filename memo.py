"""
The finalist memo.
==================

The funnel used to end in a shortlist CSV and a checklist. Neither is the artifact a
decision gets made from. This produces the thing Tal actually walks into a room with
and the thing an investor asks for: one page per finalist, base case and required
downside side by side, the open items with owners, and the two mandatory disclosures.

Generated from the same objects the model runs on, so it cannot drift from the
numbers. A memo written by hand out of a spreadsheet is the usual place reconciliation
breaks, and this removes the hand.

Status vocabulary is the project's: HAVE, DRAFT, GAP, COUNSEL.
"""
from __future__ import annotations
from typing import Optional

import decide


CONF = "PCR / Palisades — Confidential — not an offer to sell securities"

# Non-negotiable. Both appear in every memo regardless of lot, because both are true
# of the sponsor rather than of any particular parcel.
DISCLOSURES = [
    "The builder is a partner in the transaction. Construction pricing is not "
    "arm's length and has not been market-tested against an independent bid.",
    "The sponsor has no completed ground-up development as principal.",
]


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:+.0%}"


def _usd(x: Optional[float]) -> str:
    return "—" if x is None else f"${x:,.0f}"


def _verdict(margin: Optional[float]) -> tuple:
    """The band language, identical to the legend the screening table shows."""
    if margin is None:
        return "NOT PRICEABLE", "No comp basis in-jurisdiction."
    if margin <= 0:
        return "STRONG", ("Breaks even below the comparable median. The market does "
                          "not have to move for this to work.")
    if margin <= 0.10:
        return "GOOD", ("New construction normally clears a modest premium over the "
                        "median, so this clears on its own.")
    if margin <= 0.25:
        return "TIGHT", "Needs a strong market. Little room for error."
    return "DOES NOT WORK", ("No amount of negotiating on the land price closes a gap "
                             "this size.")


def build_memo(*, address: str, pf, facts: dict, verified: bool, basis: float,
               margin: Optional[float], breakeven_psf: Optional[float],
               actions: list, required: dict, option: dict,
               stability: Optional[dict] = None, build_stamp: str = "") -> str:
    """
    One page of markdown. Deliberately not a template with blanks: every figure is
    passed in from the run that produced the ranking.
    """
    band, band_note = _verdict(margin)
    prov = "CERTIFIED" if verified else "UNVERIFIED"
    comps = facts.get("comps") or []
    psfs = sorted(c["psf"] for c in comps if c.get("psf"))

    L = []
    A = L.append

    A(f"# {address}")
    A(f"*Finalist memo · status DRAFT · prior square footage {prov}*")
    A("")
    A(f"**{band}.** {band_note}")
    A("")

    # ---------------------------------------------------------------- the number
    A("## The number")
    A("")
    A("| | Base case | Required downside |")
    A("|---|---|---|")
    A(f"| Buildable | {pf.buildable_sqft:,.0f} sf | {required.get('buildable', 0):,.0f} sf |")
    A(f"| Construction | ${pf.a.construction_psf:,.0f}/sf | ${required.get('construction_psf', 0):,.0f}/sf |")
    A(f"| Schedule | {pf.a.build_months:.0f} + {pf.a.sale_months:.0f} months | "
      f"{required.get('months', 0):.0f} + {pf.a.sale_months:.0f} months |")
    A(f"| Exit basis | ${basis:,.0f}/sf | ${required.get('exit_psf', 0):,.0f}/sf |")
    A(f"| Breakeven | {_usd(breakeven_psf)}/sf | {_usd(required.get('breakeven_psf'))}/sf |")
    A(f"| **Margin over market** | **{_pct(margin)}** | **{_pct(required.get('margin'))}** |")
    A("")
    A("Margin over market is the breakeven sale price against the comparable median, "
      "not return on cost. Return on cost moves with whatever exit price is assumed, "
      "which makes it useless for ranking.")
    A("")
    if psfs:
        A(f"The matched comparable set is {len(psfs)} sales running ${min(psfs):,} to "
          f"${max(psfs):,}/sf. The comps do not reconcile tightly and no single "
          f"figure is asserted.")
        A("")

    # ------------------------------------------------------- what you must believe
    A("## What you would have to believe")
    A("")
    for m in required.get("moves", []):
        A(f"- {m}")
    A("")
    A("The right column is not a stress test. It is the case an analyst builds in "
      "the first ten minutes of diligence, so it is computed by default rather than "
      "offered as an option.")
    A("")

    # ----------------------------------------------------------------- stability
    if stability and stability.get("ok"):
        row = next((r for r in stability["rows"] if r["name"] == address), None)
        if row:
            A("## How stable is this ranking")
            A("")
            A(f"Across {stability['draws']:,} draws over the plausible input space, "
              f"this lot finishes first **{row['p_first']:.0%}** of the time and in "
              f"the top three **{row['p_top3']:.0%}** of the time. Margin over market "
              f"runs {_pct(row['margin_p10'])} to {_pct(row['margin_p90'])} across "
              f"that space, with a median of {_pct(row['margin_p50'])}.")
            co = stability.get("crossover")
            if co and co.get("note"):
                A("")
                A(co["note"])
            A("")

    # ------------------------------------------------------------- open items
    A("## Open items, ranked by what they are worth")
    A("")
    live = [a for a in actions if a["cost"] not in ("bounded",)]
    if live:
        A("| Open item | Moves the answer | Cost to resolve | Next step |")
        A("|---|---|---|---|")
        for a in live:
            A(f"| {a['name']} | {a['swing']:.0%} | {a['cost_label']} | "
              f"{a['action'].split('.')[0]}. |")
        A("")
        free = [a for a in live if a["cost"] == "free"]
        if free:
            A(f"**{len(free)} of these cost nothing and close inside a week.** "
              f"Ranked by movement per unit of effort rather than by movement alone, "
              f"because sorting on swing puts the construction bid first every time "
              f"and it is the slowest thing on the list.")
            A("")

    # --------------------------------------------------------------- structure
    if option.get("ok"):
        A("## Making the decision smaller")
        A("")
        A(option["note"])
        A("")
        A(f"*{option['no_fee_estimate']}*")
        A("")
        A("**COUNSEL** — contingency language, deposit structure, whether the deposit "
          "goes hard, and remedies are counsel items. Nothing here is a term sheet.")
        A("")

    # ------------------------------------------------------------- disclosures
    A("## Mandatory disclosures")
    A("")
    for d in DISCLOSURES:
        A(f"- {d}")
    A("")
    if not verified:
        A("- The prior square footage used above is not certified. Every "
          "prior-square-footage figure checked against LADBS records so far has been "
          "wrong and overstated. This figure has not been checked.")
        A("")

    A("---")
    A("")
    A(f"*{CONF}*" + (f"  ·  *Build {build_stamp}*" if build_stamp else ""))
    return "\n".join(L)
