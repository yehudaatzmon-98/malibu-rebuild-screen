"""
Rendering for the decision layer.

Kept out of app.py because app.py is already 1,400 lines and the calculations in
decide.py should be testable without importing Streamlit. Nothing here computes
anything; it only presents what decide.py returns.

Placement follows the same rule as the guide module: the thing that changes a
decision goes where the decision is made. Next actions and the required case sit on
the single-property view, because that is where someone is deciding. Stability and
compare sit on the shortlist, because that is where two candidates get weighed
against each other.
"""
from __future__ import annotations
import streamlit as st

import decide
import memo as memo_mod


_COST_COLOUR = {
    "free": "var(--ok)",
    "cheap": "var(--info)",
    "moderate": "var(--warn)",
    "expensive": "var(--seal)",
    "bounded": "var(--ink-faint)",
    "unresolvable": "var(--ink-faint)",
}


# ------------------------------------------------------------- 1 · next actions
def render_next_actions(actions: list) -> None:
    """
    The highest-leverage panel in the tool. Ranked by movement per unit of effort,
    which is what puts the two free lookups above the construction bid even though
    the bid has a larger raw swing.
    """
    if not actions:
        return
    live = [a for a in actions if a["cost"] not in ("bounded", "unresolvable")]
    other = [a for a in actions if a["cost"] in ("bounded", "unresolvable")]
    free = [a for a in live if a["cost"] == "free"]

    st.markdown('<div class="lbl">What to check next</div>', unsafe_allow_html=True)
    if free:
        st.markdown(
            f'<div class="cite" style="margin-bottom:10px;">'
            f'<b>{len(free)} of these cost nothing and close inside a week.</b> '
            f'Ranked by how much each moves the answer divided by what it costs to '
            f'find out, not by movement alone — sorting on movement puts the '
            f'construction bid first every time, and it is the slowest thing on the '
            f'list.</div>', unsafe_allow_html=True)

    for a in live:
        col = _COST_COLOUR.get(a["cost"], "var(--ink)")
        st.markdown(
            f'<div class="card" style="border-left-color:{col};">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
            f'<b>{a["name"]}</b>'
            f'<span class="mono" style="font-size:0.95rem;font-weight:700;color:{col};">'
            f'moves {a["swing"]:.0%}</span></div>'
            f'<div class="lbl" style="color:{col}!important;margin:4px 0 6px;">'
            f'{a["cost_label"]}</div>'
            f'<div class="cite"><b>Do this:</b> {a["action"]}<br><br>{a["why"]}</div>'
            f'</div>', unsafe_allow_html=True)

    for a in other:
        st.markdown(
            f'<div class="card card-none">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
            f'<b>{a["name"]}</b><span class="mono" style="font-size:0.9rem;">'
            f'range {a["swing"]:.0%}</span></div>'
            f'<div class="lbl" style="margin:4px 0 6px;">{a["cost_label"]}</div>'
            f'<div class="cite">{a["why"]}</div></div>', unsafe_allow_html=True)


# --------------------------------------------------------- 2 · required downside
def render_required_case(required: dict, base_margin, base_breakeven, basis) -> None:
    """
    Always shown, never behind a slider. A model whose lowest case is the market
    median has no downside in it, and an analyst will build this in ten minutes
    anyway.
    """
    if not required or not required.get("ok"):
        return
    m = required.get("margin")
    st.markdown('<div class="lbl">Required downside case</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div class="card"><div class="lbl">Base case</div>'
            f'<div class="big">{"—" if base_margin is None else f"{base_margin:+.0%}"}</div>'
            f'<div class="cite">margin over market · breaks even at '
            f'${(base_breakeven or 0):,.0f}/sf against a median of ${(basis or 0):,.0f}'
            f'</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div class="card card-pass"><div class="lbl">Required downside</div>'
            f'<div class="big">{"—" if m is None else f"{m:+.0%}"}</div>'
            f'<div class="cite">breaks even at '
            f'${(required.get("breakeven_psf") or 0):,.0f}/sf against an exit of '
            f'${required.get("exit_psf", 0):,.0f}/sf</div></div>',
            unsafe_allow_html=True)
    st.markdown(
        '<div class="cite" style="margin:8px 0 4px;"><b>The downside holds these '
        'four things:</b></div>', unsafe_allow_html=True)
    for mv in required.get("moves", []):
        st.markdown(f'<div class="cite">· {mv}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="cite" style="margin-top:8px;">This is not a stress test. It is '
        'the case an analyst builds in the first ten minutes of diligence, so it is '
        'computed by default rather than offered as an option.</div>',
        unsafe_allow_html=True)


# ------------------------------------------------------- 3 · make it smaller
def render_option(option: dict) -> None:
    if not option or not option.get("ok"):
        return
    st.markdown('<div class="lbl">Making the decision smaller</div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div class="card"><div class="cite">{option["note"]}<br><br>'
        f'<i>{option["no_fee_estimate"]}</i><br><br>'
        f'<b>COUNSEL</b> — contingency language, deposit structure, whether the '
        f'deposit goes hard, and remedies are counsel items. Nothing here is a term '
        f'sheet.</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------- 4 · stability
def render_stability(st_res: dict) -> None:
    """
    Runs on the shortlist rather than the full batch: stability matters between
    finalists, and sweeping 150 lots would cost a minute for no decision value.
    """
    if not st_res or not st_res.get("ok"):
        if st_res and st_res.get("note"):
            st.markdown(f'<div class="cite">{st_res["note"]}</div>',
                        unsafe_allow_html=True)
        return
    st.markdown('<div class="lbl">How stable is this ranking</div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div class="cite" style="margin-bottom:10px;">Each shortlisted lot swept '
        f'{st_res["draws"]:,} times across the plausible input space: exit price '
        f'resampled from its own matched comps, construction across the band, '
        f'schedule 30 to 35 months, and unverified square footage carrying the '
        f'one-sided overstatement observed on five of five LADBS checks. '
        f'<b>A lot that wins often but sits outside the top three half the time is a '
        f'different proposition from one that is nearly always near the front.</b>'
        f'</div>', unsafe_allow_html=True)
    for r in st_res["rows"]:
        st.markdown(
            f'<div class="card"><div style="display:flex;justify-content:space-between;'
            f'align-items:baseline;"><b>{r["name"]}</b>'
            f'<span class="mono" style="font-weight:700;">first {r["p_first"]:.0%} · '
            f'top three {r["p_top3"]:.0%}</span></div>'
            f'<div class="cite">margin over market runs '
            f'{r["margin_p10"]:+.0%} to {r["margin_p90"]:+.0%} across that space, '
            f'median {r["margin_p50"]:+.0%}</div></div>', unsafe_allow_html=True)
    co = st_res.get("crossover")
    if co and co.get("note"):
        st.markdown(f'<div class="card card-none"><div class="cite"><b>Crossover.</b> '
                    f'{co["note"]}</div></div>', unsafe_allow_html=True)


# --------------------------------------------------------------- 5 · compare
def render_compare(rows: list) -> None:
    """
    Two or three finalists on identical axes, differences visible. The line at the
    bottom — what would have to be true for the runner-up to win — is usually the
    most informative thing on the page.
    """
    if len(rows) < 2:
        return
    import pandas as pd
    axes = ["Margin over market", "Required downside", "Buildable sf",
            "Construction $/sf", "Breakeven $/sf", "Comp basis $/sf", "Ask",
            "$/buildable ft", "Verified", "Free checks outstanding"]
    table = {"": axes}
    for r in rows[:3]:
        table[r["name"]] = [
            "—" if r["margin"] is None else f"{r['margin']:+.0%}",
            "—" if r["required"].get("margin") is None else f"{r['required']['margin']:+.0%}",
            f"{r['pf'].buildable_sqft:,.0f}",
            f"${r['pf'].a.construction_psf:,.0f}",
            f"${(r['breakeven'] or 0):,.0f}",
            f"${(r['basis'] or 0):,.0f}",
            f"${r['pf'].land_cost:,.0f}",
            f"${(r['pf'].land_cost / r['pf'].buildable_sqft):,.0f}"
            if r["pf"].buildable_sqft else "—",
            "yes" if r["verified"] else "no",
            str(len([a for a in r["actions"] if a["cost"] == "free"])),
        ]
    st.markdown('<div class="lbl">Finalists, side by side</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    a, b = rows[0], rows[1]
    if a["margin"] is not None and b["margin"] is not None:
        gap = b["margin"] - a["margin"]
        st.markdown(
            f'<div class="card card-none"><div class="cite">'
            f'<b>What would have to be true for {b["name"]} to win.</b> It currently '
            f'breaks even {abs(gap):.0%} '
            f'{"further above" if gap > 0 else "below"} the market than '
            f'{a["name"]}. Closing that on land price alone means paying about '
            f'{abs(gap) * 100 / 100:.0%} less for it, or roughly '
            f'${abs(gap) * b["pf"].land_cost:,.0f} off the ask, holding everything '
            f'else. If the gap is larger than any discount you would realistically '
            f'get, the ordering is not a negotiation question.'
            f'</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ 6 · memo
def render_memo_download(*, address, pf, facts, verified, basis, margin,
                         breakeven, actions, required, option, stability,
                         build_stamp) -> None:
    md = memo_mod.build_memo(
        address=address, pf=pf, facts=facts, verified=verified, basis=basis,
        margin=margin, breakeven_psf=breakeven, actions=actions, required=required,
        option=option, stability=stability, build_stamp=build_stamp)
    st.download_button(
        "Download the finalist memo",
        md, f"{address.replace(' ', '_').replace('/', '-')}_memo.md", "text/markdown",
        help="One page, generated from the same numbers this screen is showing, so "
             "it cannot drift from the model. Base case and required downside side "
             "by side, open items with what each is worth, and the two mandatory "
             "disclosures.")
