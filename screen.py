"""
Malibu Rebuild Screen — the tool Tal actually uses.

One job: take a Redfin export of new listings and tell him which are worth an
afternoon. Enriches every row from the LA County Assessor (live), applies
Interpretation No. 24, and returns a verdict per lot with the rule cited.

Not a valuation. It answers "is this worth looking at" — the only question that
matters when you need 15 lots and have 7.

Run:  streamlit run screen.py
"""
import io
import re
import pandas as pd
import streamlit as st

from county import (lookup, triage, envelope, envelope_both_cases, ceiling_from_year,
                    split_address, ceiling_sensitivity, spr_check, purchaser_diligence,
                    realistic_program, access_dedication_warning, height_conformity_flag,
                    pf1_check, tdsf_cap, beachfront_fork, baseline_provenance_warning,
                    the_record_exists, design_out_of_it, issue10_exposure, nollan_reality,
                    thesis_fit, entitlement_status)
import jurisdiction as jur
from engine import (Assumptions, CompMarket, ProForma, what_youd_have_to_believe,
                    discount_to_breakeven)
import pandas as _pd

st.set_page_config(page_title="Rebuild Screen", layout="wide",
                   initial_sidebar_state="collapsed")

# money engine — comps loaded once, shared with the batch analyzer
@st.cache_data
def _load_comps():
    try:
        return _pd.read_csv("comps_database.csv")
    except Exception:
        return None

_COMPS = _load_comps()
_MKT = CompMarket(_COMPS) if _COMPS is not None else None


def render_money(jurisdiction_code, buildable_sqft, ask_price, express, lat=None, lon=None):
    """The return, inline, led by a plain-language call-it / kill-it verdict and the
    walk-away number — the thing Michael can act on — with the arithmetic below."""
    if not buildable_sqft:
        return
    if _MKT is None:
        st.markdown('<div class="card card-note"><span class="cite">Comp database not '
                    'loaded — can\'t compute the return. Add comps_database.csv beside '
                    'the app.</span></div>', unsafe_allow_html=True)
        return
    m = _MKT.match(jurisdiction_code, buildable_sqft, lat, lon)
    a_ = Assumptions()
    if not m.get("basis"):
        st.markdown(
            f'<div class="card card-none"><span class="stamp s-none">NO COMP BASIS</span>'
            f'<br><span class="cite">{m["note"]}<br><br>Envelope is <b>{buildable_sqft:,.0f} '
            f'sf</b> — buildable, but not priceable from the loaded comps.</span></div>',
            unsafe_allow_html=True)
        return
    # a placeholder or missing price can't be priced — same discipline as the batch.
    if not ask_price or float(ask_price) <= 1000:
        st.markdown(
            f'<div class="card card-note"><span class="stamp s-none">NEED PRICE</span><br>'
            f'<b>Comps say ~${m["basis"]:,}/sf</b> ({m["n"]} matched, ${m["low"]:,}–${m["high"]:,}). '
            f'Buildable ~{buildable_sqft:,.0f} sf.<br>'
            f'<span class="cite">Enter the real asking price above for the return — it\'s the '
            f'land cost. Don\'t leave a placeholder; the signal is meaningless without it.</span>'
            f'</div>', unsafe_allow_html=True)
        return
    pf = ProForma(buildable_sqft, float(ask_price), m["basis"], jurisdiction_code, a_,
                  express=express, comp_low=m["low"], comp_high=m["high"])
    r = pf.run()
    b = r["base"]
    sig = r["signal"]
    sig_cls = {"STRONG": "s-strong", "BUY": "s-buy", "MAYBE": "s-maybe",
               "PASS": "s-pass"}.get(sig, "s-none")
    lo_roc, hi_roc = r["low"]["roc"], r["high"]["roc"]
    w = what_youd_have_to_believe(pf)
    dtb = discount_to_breakeven(pf)

    # the one-line call, in plain language
    if sig in ("STRONG", "BUY"):
        call = "Worth a call."
    elif sig == "MAYBE":
        call = "Borderline — call only if the walk-away price is realistic."
    else:
        call = "Skip it, unless the price moves a lot."
    walk = dtb.get("verdict", "") if dtb.get("ok") else ""

    st.markdown(f"""
<div class="card card-money">
  <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:6px;">
    <span class="stamp {sig_cls}" style="font-size:0.95rem;">{sig}</span>
    <span class="big">{b['roc']:.0%}</span>
    <span class="lbl">return on cost, at ${float(ask_price):,.0f} ask</span>
  </div>
  <div style="font-size:1.05rem;font-weight:600;margin-bottom:4px;">{call}</div>
  <span class="cite">
  <b>Your number before you call the agent:</b> {walk}<br>
  Range <b>{lo_roc:.0%}</b> to <b>{hi_roc:.0%}</b> across the comp spread — a sort order, not a green light.
  </span>
  <details style="margin-top:10px;">
    <summary class="cite" style="cursor:pointer;font-weight:600;">Show the arithmetic</summary>
    <span class="cite">
    &nbsp;&nbsp;buildable &nbsp; <b>{buildable_sqft:,.0f} sf</b><br>
    &nbsp;&nbsp;exit basis &nbsp; ${m['basis']:,}/sf → ${b['effective_psf']:,}/sf after escalation + premium<br>
    &nbsp;&nbsp;land &nbsp; ${float(ask_price):,.0f}<br>
    &nbsp;&nbsp;construction &nbsp; ${b['construction']:,.0f} &nbsp;·&nbsp; contingency ${b['contingency']:,.0f}
    &nbsp;·&nbsp; carry ${b['carry']:,.0f}<br>
    &nbsp;&nbsp;total cost &nbsp; <b>${b['total_cost']:,.0f}</b><br>
    &nbsp;&nbsp;net sale &nbsp; ${b['net_sale']:,.0f} &nbsp;·&nbsp; profit <b>${b['profit']:,.0f}</b><br>
    &nbsp;&nbsp;<span style="font-size:0.75rem;">Yardstick: {a_.stamp()}</span>
    </span>
  </details>
</div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- type & tone
# The subject's world is the municipal record: assessor rolls, parcel maps, a
# numbered interpretation. Typography borrows from that — a condensed grotesk for
# the record-keeping voice, monospace for every figure, because every figure here
# is evidence and should read as transcribed rather than designed.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

/* ---------------------------------------------------------------------------
   This is a municipal record, not a terminal. Assessor rolls, a numbered
   ordinance, evidence you'd hand a lawyer. So: paper, not black glass.
   Ink on off-white, a text face with real authority for prose, mono reserved
   strictly for figures because every figure here is transcribed from a record.
   --------------------------------------------------------------------------- */

:root {
  --paper:      #faf9f6;   /* off-white, warm, low glare */
  --paper-2:    #f2f0ea;   /* recessed panels */
  --ink:        #16150f;   /* body */
  --ink-soft:   #55524a;   /* secondary */
  --ink-faint:  #6b6860;   /* captions - darkened to clear WCAG AA on paper */
  --rule:       #ddd9cd;   /* hairlines */
  --seal:       #7a2518;   /* oxblood — the stamp colour */
  --ok:         #1f5c2e;
  --warn:       #8a5a00;
  --info:       #1b4f6b;
}

.stApp { background: var(--paper); }
html, body, [class*="css"], .stMarkdown, .stMarkdown p,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p {
  font-family: 'Inter', system-ui, sans-serif;
  color: var(--ink) !important;
  font-size: 1rem;
  line-height: 1.62;
}
h1,h2,h3,h4 { font-family:'Newsreader', Georgia, serif !important; color: var(--ink) !important;
              letter-spacing:-0.01em; font-weight:600; }

/* masthead ---------------------------------------------------------------- */
.masthead { border-bottom: 3px double var(--rule); padding-bottom: 16px; margin-bottom: 20px; }
.title { font-family:'Newsreader', Georgia, serif; font-size:2.9rem; font-weight:700;
         letter-spacing:-0.02em; color:var(--ink); line-height:1.05; margin:0 0 10px 0; }
.rule-cite { font-family:'JetBrains Mono',monospace; font-size:0.7rem; color:var(--ink-faint);
             letter-spacing:0.02em; line-height:1.7; }

/* verdict — a stamp on a form ---------------------------------------------- */
.stamp { font-family:'JetBrains Mono',monospace; font-size:0.78rem; font-weight:700;
         letter-spacing:0.14em; padding:5px 12px; border:2px solid; display:inline-block;
         text-transform:uppercase; background:var(--paper); }
.s-elig { color:var(--ok);   border-color:var(--ok); }
.s-excl { color:var(--seal); border-color:var(--seal); }
.s-unsc { color:var(--warn); border-color:var(--warn); }
.s-rev  { color:var(--info); border-color:var(--info); }
.s-strong { color:var(--ok);   border-color:var(--ok); }
.s-buy    { color:var(--info); border-color:var(--info); }
.s-maybe  { color:var(--warn); border-color:var(--warn); }
.s-pass   { color:var(--seal); border-color:var(--seal); }
.s-none   { color:var(--ink-faint); border-color:var(--ink-faint); }
.big { font-family:'JetBrains Mono',monospace; font-size:1.9rem; font-weight:700;
       color:var(--ink); line-height:1; }
.lbl { font-family:'Inter',sans-serif; font-size:0.68rem; color:var(--ink-faint) !important;
       letter-spacing:0.09em; text-transform:uppercase; font-weight:600; }

/* figures — transcribed, so mono ------------------------------------------- */
.mono { font-family:'JetBrains Mono',monospace; }
.figure { font-family:'JetBrains Mono',monospace; font-size:2.1rem; font-weight:700;
          color:var(--ink); line-height:1.1; }
.figure-label { font-family:'Inter',sans-serif; font-size:0.72rem; color:var(--ink-faint) !important;
                letter-spacing:0.09em; text-transform:uppercase; font-weight:600; margin-bottom:4px; }
.binding { font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--seal);
           font-weight:600; }

/* cards — a sheet clipped to the file -------------------------------------- */
.card { background:#fff; border:1px solid var(--rule); border-left:3px solid var(--ink);
        padding:18px 20px; margin-bottom:12px; font-size:0.95rem; line-height:1.65;
        color:var(--ink) !important; }
.card * { color:var(--ink) !important; }
.card b { font-weight:650; }
.card-warn { border-left-color: var(--seal); background:#fffcfb; }
.card-note { border-left-color: var(--ink-faint); background:var(--paper-2); }
.card-none { border-left-color: var(--ink-faint); background:var(--paper-2); }
.card-money { border-left-width:3px; border-left-color: var(--ink); background:#fffef9;
              border-top:1px solid var(--rule); }

/* captions — small but READABLE. never below 0.78rem, never below 4.5:1 ---- */
.cite, .cite * { font-family:'Inter',sans-serif !important; font-size:0.82rem !important;
        color:var(--ink-soft) !important; line-height:1.6; letter-spacing:0; }

.ledger-row, .ledger-row * { border-bottom:1px solid var(--rule); padding:11px 0;
              font-family:'Inter',sans-serif !important; font-size:0.92rem !important;
              color:var(--ink) !important; line-height:1.6; }
.ledger-row .mono { font-family:'JetBrains Mono',monospace !important; }

.sourced { color:var(--ok) !important; font-family:'JetBrains Mono',monospace;
           font-size:0.68rem; font-weight:700; letter-spacing:0.08em; }
.assumed { color:var(--warn) !important; font-family:'JetBrains Mono',monospace;
           font-size:0.68rem; font-weight:700; letter-spacing:0.08em; }

hr { border:none; border-top:1px solid var(--rule); margin:22px 0; }

/* controls ----------------------------------------------------------------- */
/* Buttons.
   Streamlit nests the label in a <p> inside the <button>, and the global
   `.stMarkdown p { color: ... !important }` above wins over the button's own
   colour — giving black text on a black button. Target the descendants
   explicitly, with !important, or the label disappears. */
.stButton>button, .stButton>button *,
.stDownloadButton>button, .stDownloadButton>button * {
  font-family:'Inter',sans-serif !important; font-weight:600 !important;
  letter-spacing:0.02em; color:var(--paper) !important; }
.stButton>button, .stDownloadButton>button {
  border-radius:2px; border:1.5px solid var(--ink); background:var(--ink);
  padding:8px 22px; }
.stButton>button:hover, .stDownloadButton>button:hover {
  background:var(--seal); border-color:var(--seal); }
.stButton>button:hover *, .stDownloadButton>button:hover * { color:#fff !important; }
.stButton>button:focus-visible, .stDownloadButton>button:focus-visible {
  outline:3px solid var(--info); outline-offset:2px; }

label, .stTextInput label, .stNumberInput label, .stSelectbox label,
[data-testid="stWidgetLabel"] p {
  font-family:'Inter',sans-serif !important; font-size:0.82rem !important;
  font-weight:600 !important; color:var(--ink) !important; letter-spacing:0.01em; }

.stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
  background:#fff !important; color:var(--ink) !important;
  border:1.5px solid var(--rule) !important; border-radius:2px !important;
  font-family:'JetBrains Mono',monospace !important; }
.stTextInput input:focus, .stNumberInput input:focus { border-color:var(--ink) !important; }

/* The +/- steppers on number inputs are <button> elements, so the primary button
   rule above would paint them solid ink. They're secondary controls — keep them
   quiet: ink on paper, not paper on ink. */
.stNumberInput button, .stNumberInput button * {
  background:var(--paper-2) !important; color:var(--ink) !important;
  border:1px solid var(--rule) !important; }
.stNumberInput button:hover, .stNumberInput button:hover * {
  background:var(--rule) !important; color:var(--ink) !important; }

/* THE FIX: tooltips were white-on-white and unreadable ---------------------- */
[data-baseweb="tooltip"], [data-baseweb="tooltip"] *, div[role="tooltip"], div[role="tooltip"] * {
  background:var(--ink) !important; color:var(--paper) !important;
  font-family:'Inter',sans-serif !important; font-size:0.84rem !important;
  line-height:1.6 !important; border-radius:3px !important; max-width:420px !important; }

.stExpander { border:1px solid var(--rule) !important; border-radius:2px; background:#fff; }
.stExpander p, .stExpander label, [data-testid="stExpander"] summary,
[data-testid="stExpander"] summary * { color:var(--ink) !important; }
[data-testid="stExpander"] summary { font-family:'Inter',sans-serif !important;
                                     font-weight:600 !important; font-size:0.95rem !important; }
.stTabs [data-baseweb="tab"] { font-family:'Inter',sans-serif; font-weight:600;
                               color:var(--ink-soft); font-size:0.95rem; }
.stTabs [aria-selected="true"] { color:var(--ink) !important; }
.stProgress > div > div > div { background:var(--ink) !important; }

@media (prefers-reduced-motion: reduce) { * { animation:none !important; transition:none !important; } }
</style>
""", unsafe_allow_html=True)


def stamp(v):
    cls = {"ELIGIBLE": "s-elig", "SCOREABLE": "s-elig", "EXCLUDED": "s-excl",
           "UNSCOREABLE": "s-unsc", "REVIEW": "s-rev"}.get(v, "s-rev")
    return f'<span class="stamp {cls}">{v}</span>'


# ---------------------------------------------------------------- masthead
st.markdown("""
<div class="masthead">
  <div class="title">Rebuild Screen</div>
  <div class="rule-cite">
  MALIBU &nbsp;LCP &amp; Zoning Code Interpretation No. 24 &nbsp;·&nbsp; adopted 15 Oct 2025<br>
  CITY OF LA &nbsp;Emergency Executive Order 1 (rev. 18 Mar 2025) &amp; EO8 (23 Jul 2025)<br>
  PARCEL DATA &nbsp;LA County Assessor, live &nbsp;·&nbsp; routed per parcel
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
Drop in a Redfin export of new listings. Every address is checked against the County
Assessor for what actually burned, routed to the rulebook that governs **that parcel**,
and returned with a verdict and the rule that produced it.

**This is not a valuation.** It answers one question: *is this lot worth your afternoon?*

The fire crossed a city line; the rules did not. Malibu caps bulk, square footage **and**
height at 110% — so raising ceilings costs you area. The City of LA caps footprint and
height only — so it doesn't. A parcel is never screened under a rule it isn't subject to.
""")

# ---------------------------------------------------------------- what Tal decides
with st.expander("What you'd build — your calls, not the rule's", expanded=False):
    st.markdown('<span class="cite">The rule is fixed. These are not. Every figure here is '
                'yours and travels with the output.</span>', unsafe_allow_html=True)
    st.write("")
    c1, c2, c3 = st.columns(3)
    with c1:
        proposed_ceiling = st.number_input(
            "Ceiling height you'd build (ft)", 8.0, 14.0, 10.0, 0.5,
            help="Malibu only. Build to 8.5ft and you get the full +10%; build to 10ft and "
                 "the volume cap bites. No effect on City of LA lots.")
        st.markdown('<span class="cite">Biggest lever in the Malibu rule. Raise it and the '
                    'volume cap bites before you reach the +10%.</span>',
                    unsafe_allow_html=True)
    with c2:
        basement = st.number_input(
            "Basement / subterranean garage (sf)", 0, 5000, 0, 100,
            help="Counts toward the same 110% (Issue No. 5).")
        st.markdown('<span class="cite">Counts against the same 110% and returns nothing '
                    'per finished foot. Comes straight out of habitable area.</span>',
                    unsafe_allow_html=True)
    with c3:
        prior_override = st.number_input(
            "Prior ceiling height, if you know it (ft)", 0.0, 14.0, 0.0, 0.5,
            help="Leave at 0 and the tool guesses from year built.")
        st.markdown('<span class="cite"><b>Leave 0 and the tool guesses.</b> That guess is '
                    'unsourced and it drives the volume ceiling. The pre-fire listing '
                    'usually states ceiling height — enter it here.</span>',
                    unsafe_allow_html=True)

    st.markdown("")
    c4, c5 = st.columns(2)
    with c4:
        bf = st.selectbox(
            "Beachfront? (Malibu only — Issue No. 9)",
            ["Unknown", "Beachfront", "Non-beachfront"],
            help="NOT in the county record. On NON-beachfront Malibu lots, any increase "
                 "above 18ft needs Site Plan Review — so the +10% is DISCRETIONARY, not "
                 "ministerial. Five of the seven PCH lots are Las Flores, non-beachfront. "
                 "Determinable per parcel from the City's GIS layers.")
        beachfront = {"Unknown": None, "Beachfront": True, "Non-beachfront": False}[bf]
    with c5:
        spend = st.selectbox(
            "How you'd spend the +10%",
            ["Laterally (prior roofline)", "Vertically (taller)"],
            help="The SPR trigger is the INCREASE above 18ft, not the structure's height.")
        spend_vert = spend.startswith("Vertically")
        st.markdown('<span class="cite">The SPR trigger is the <i>increase</i> above 18ft, '
                    'not the structure. Rebuild a 24ft house at 24ft and nothing is '
                    'increased. Take it laterally and SPR goes away — and since the '
                    'allowance is bulk-constrained anyway, that\'s close to free.</span>',
                    unsafe_allow_html=True)

    st.markdown("")
    ce1, ce2 = st.columns([1, 1])
    with ce1:
        plans = st.selectbox(
            "Does the lot already have plans / permits?",
            ["None", "Application in process", "Approved / ready-to-issue"],
            help="Approved plans ARE the envelope — they moot the rebuild math entirely.")
        plans_state = {"None": "NONE", "Application in process": "IN_PROCESS",
                       "Approved / ready-to-issue": "APPROVED"}[plans]
        st.markdown('<span class="cite">If a lot arrives entitled, the plans are the '
                    'envelope and the rebuild rule doesn\'t govern. This is the strongest '
                    'status a lot can have — it ranks at the top.</span>',
                    unsafe_allow_html=True)
    with ce2:
        plan_sf = st.number_input(
            "Approved plan sqft (if known)", 0, 20000, 0, 100,
            help="From the stamped plan set or the listing (e.g. 'plans for 5,200 sf approved').")

    st.markdown("")
    c6, c7 = st.columns(2)
    with c6:
        hc = st.selectbox(
            "Prior structure height conformity",
            ["Unknown", "Conforming", "Nonconforming"],
            help="Decides whether the Issue No. 10 downside is a fee or a redesign.")
        height_conf = {"Unknown": None, "Conforming": True, "Nonconforming": False}[hc]
        st.markdown('<span class="cite">If the prior structure was <b>nonconforming in '
                    'height</b>, the certified de minimis waiver allows <b>no additional '
                    'height at all</b>. Old Malibu beach stock frequently is. Get it from '
                    'the survey and permit record before closing.</span>',
                    unsafe_allow_html=True)
    with c7:
        over_cap = st.checkbox(
            "Model a build that EXCEEDS the 10% cap",
            help="On beachfront this may cost a permanent public access dedication.")
        st.markdown('<span class="cite">On beachfront, breaking the cap makes you '
                    '&quot;new development&quot; for PRC 30212 — which requires public '
                    'access to the shoreline. Not a timeline problem. An exit '
                    'problem.</span>', unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------- input
tab_batch, tab_one = st.tabs(["Screen a Redfin export", "Check one address"])

with tab_one:
    ca1, ca2, ca3, ca4 = st.columns([3, 1, 1, 1])
    with ca1:
        a = st.text_input("Address", placeholder="20610 Pacific Coast Hwy")
    with ca2:
        ask_price = st.number_input(
            "Asking price ($)", 0, 100_000_000, 0, 50_000,
            help="The list or offer price. Needed for the return — it's the land cost in "
                 "the pro forma. Leave 0 to see the envelope and comps without the return.")
    with ca3:
        claimed = st.number_input(
            "Prior sf the listing claims", 0, 50000, 0, 50,
            help="What the listing says burned. The tool compares it to the county record.")
    with ca4:
        storeys_in = st.number_input(
            "Storeys (LA only)", 0, 4, 0, 1,
            help="From the pre-fire sale listing. City of LA lots only. 0 if unknown.")
    st.markdown('<span class="cite">'
                '<b>Prior sf the listing claims</b> — the tool checks it against the county. '
                'Live examples: 20048 PCH claimed 2,452 against a record of 1,671 (+47%); '
                '16767 Bollinger claimed 4,527 against 3,339 (+36%). &nbsp;·&nbsp; '
                '<b>Storeys</b> — read it off the pre-fire sale listing, which describes the '
                'house floor by floor. Burned lots nearly always have one in the MLS archive. '
                'Only used on City of LA lots, where EO1 caps footprint rather than square '
                'footage.</span>', unsafe_allow_html=True)
    st.write("")
    if st.button("Check it") and a:
        with st.spinner("Pulling the county record…"):
            p = lookup(a)
        if not p.found:
            st.markdown(f'{stamp("UNSCOREABLE")}', unsafe_allow_html=True)
            st.markdown(f'<div class="card mono">{p.note}</div>', unsafe_allow_html=True)
        else:
            t = triage(p, listing_sqft=claimed or None, storeys=storeys_in or None)
            j = jur.route(p.situs_city)
            # Approved plans moot the footprint question in EITHER jurisdiction.
            _ent = entitlement_status(plans_state, plan_sf or None, beachfront)
            if _ent and _ent["ranks_top"]:
                st.markdown(f'{stamp("ELIGIBLE")}  <span class="cite">already entitled</span>',
                            unsafe_allow_html=True)
                st.markdown(f'<div class="card">{_ent["note"]}</div>', unsafe_allow_html=True)
                st.markdown('<span class="cite">The rule readout below is context only — '
                            'the approved plans govern, not the rebuild math.</span>',
                            unsafe_allow_html=True)
            st.markdown(f'{stamp(t.verdict)}  <span class="cite">{j.name}'
                        f'{" · " + t.rule if t.rule else ""}</span>',
                        unsafe_allow_html=True)

            # ---- THE RETURN, INLINE — the analyzer's money case on this one lot ----
            # Compute the buildable number for whichever jurisdiction, then price it.
            _build = None
            _express = True
            if _ent and _ent["ranks_top"] and plan_sf:
                _build = plan_sf  # approved plans ARE the envelope
            elif t.jurisdiction == jur.MALIBU and p.prior_sqft:
                _ph, _ = ceiling_from_year(p.year_built, prior_override or None)
                if _ph:
                    _build = envelope_both_cases(
                        p.prior_sqft, _ph, proposed_ceiling, basement
                    )["as_of_right"]["habitable"]
                _express = True
            elif j.code == jur.CITY_OF_LA and p.prior_sqft:
                _est = jur.la_envelope_estimate(p.prior_sqft, lot_sqft=p.lot_sqft,
                                                storeys=storeys_in or None)
                _build = _est.get("base")
                _express = False
            if _build:
                render_money(j.code, _build, ask_price, _express,
                             lat=getattr(p, "lat", None), lon=getattr(p, "lon", None))

            if p.note:
                st.markdown(f'<div class="card mono" style="font-size:0.75rem">{p.note}</div>',
                            unsafe_allow_html=True)
            _rule_label = ("The rebuild rules for this lot"
                           if j.code == jur.MALIBU else
                           "How this lot can be built (City of LA — EO1/EO8)")
            with st.expander(_rule_label, expanded=False):
                st.markdown(f'<div class="card">{t.reason}</div>', unsafe_allow_html=True)
            # Envelope math is Interp. No. 24 — Malibu only. Never run it elsewhere.
            if t.verdict == "ELIGIBLE" and t.jurisdiction == jur.MALIBU and p.prior_sqft:
                ent = entitlement_status(plans_state, plan_sf or None, beachfront)
                if ent:
                    css = "card" if ent["ranks_top"] else "card card-note"
                    st.markdown(f'<div class="{css}">{ent["note"]}</div>',
                                unsafe_allow_html=True)
                st.markdown(f'<div class="card">{thesis_fit(p.prior_sqft, beachfront)}</div>',
                            unsafe_allow_html=True)
                st.markdown(f'<div class="card card-warn">'
                            f'{baseline_provenance_warning(p)}</div>',
                            unsafe_allow_html=True)
                st.markdown(f'<div class="card card-note">{beachfront_fork(beachfront)}</div>',
                            unsafe_allow_html=True)
                cliff = access_dedication_warning(beachfront, over_cap)
                if cliff:
                    st.markdown(f'<div class="card card-warn">{cliff}</div>',
                                unsafe_allow_html=True)
                    if beachfront:
                        st.markdown(f'<div class="card">{nollan_reality()}</div>',
                                    unsafe_allow_html=True)
                spr = spr_check(beachfront, proposed_ceiling, 1,
                                spend_allowance_vertically=spend_vert)
                if spr:
                    st.markdown(f'<div class="card">{spr}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="card card-note">'
                            f'{height_conformity_flag(conforming=height_conf)}</div>',
                            unsafe_allow_html=True)
                with st.expander("Issue No. 10 — the exposure everyone models wrong",
                                 expanded=False):
                    st.markdown(f'<div class="card card-warn">{issue10_exposure()}</div>',
                                unsafe_allow_html=True)
                ph, basis = ceiling_from_year(p.year_built, prior_override or None)
                if ph:
                    both = envelope_both_cases(p.prior_sqft, ph, proposed_ceiling, basement)
                    aor, ifg = both["as_of_right"], both["if_granted"]
                    e = ifg  # kept for the working below
                    k1, k2, k3 = st.columns(3)
                    with k1:
                        st.markdown(f'<div class="figure-label">what burned</div>'
                                    f'<div class="figure">{p.prior_sqft:,}</div>'
                                    f'<span class="assumed">ASSESSOR · NOT A SURVEY</span>',
                                    unsafe_allow_html=True)
                    with k2:
                        st.markdown(f'<div class="figure-label">as of right</div>'
                                    f'<div class="figure">{aor["habitable"]:,}</div>'
                                    f'<span class="sourced">CRITERIA-BASED · LIP 13.4.6</span>',
                                    unsafe_allow_html=True)
                    with k3:
                        st.markdown(f'<div class="figure-label">if the +10% is granted</div>'
                                    f'<div class="figure">{ifg["habitable"]:,}</div>'
                                    f'<span class="assumed">DISCRETIONARY · MMC 17.60.020(C)</span>',
                                    unsafe_allow_html=True)

                    st.markdown(f"""<div class="card card-warn">
                    <b>The +10% is a discretionary grant, not an entitlement.</b><br>
                    Two instruments are doing work here and they have different characters.
                    The CDP exemption (LIP 13.4.6) is <b>criteria-based</b> — same use, within
                    10% of floor area/height/bulk, substantially the same location. Meet the
                    three tests, no permit, no discretion. But the zoning +10%
                    (MMC 17.60.020(C), as amended by Ordinance 524) reads: structures
                    <i>"may be permitted, <b>at the discretion of the planning director</b>
                    through approval of a planning verification, to increase the square
                    footage, height or bulk permitted by this title by 10 percent."</i><br><br>
                    Interpretation No. 24 spends twelve issues on <i>how</i> to calculate it,
                    not <i>whether</i> to grant it, which suggests routine administrative grant.
                    <b>But that is an inference, not evidence</b> — and the evidence is
                    obtainable (see below). The code text doesn't support underwriting it as
                    certain, and it's the obvious lever if anyone wanted one.<br><br>
                    <b>Here it's worth {ifg['gross'] - aor['gross']:,} sf.</b> Model
                    {aor['habitable']:,} as the base case — not because it'll be denied, but
                    because {ifg['gross'] - aor['gross']:,} sf shouldn't decide anything.
                    </div>""", unsafe_allow_html=True)

                    with st.expander("No grant rate exists — but the record does", expanded=False):
                        st.markdown(f'<div class="card">{the_record_exists()}</div>',
                                    unsafe_allow_html=True)
                        st.markdown(f'<div class="card card-warn">{design_out_of_it()}</div>',
                                    unsafe_allow_html=True)
                    st.markdown(f"""<div class="card mono" style="font-size:0.75rem">
                    sqft ceiling &nbsp; {p.prior_sqft:,} × 1.10 = <b>{e['sqft_cap']:,}</b><br>
                    volume ceiling &nbsp; ({p.prior_sqft:,} × {ph}ft × 1.10) ÷ {proposed_ceiling}ft = <b>{e['vol_cap']:,}</b><br>
                    <span class="binding">→ {e['binding']} binds at {e['gross']:,} sf</span><br>
                    <span class="cite">prior ceiling: {basis}</span>
                    </div>""", unsafe_allow_html=True)

                    rp = realistic_program(p.prior_sqft, ph, proposed_ceiling, basement,
                                           lot_sqft=p.lot_sqft, is_beachfront=beachfront)
                    st.markdown(f"""<div class="card">
                    <b>What you can actually build without a CDP</b><br>
                    Primary as of right <b>{rp['primary_as_of_right']:,} sf</b> &nbsp;·&nbsp;
                    if the +10% is granted <b>{rp['primary_if_granted']:,} sf</b><br>
                    Plus an <b>ADU up to {rp['adu_max']:,} sf</b> — Ordinance 524's cap, with the
                    garage (400 sf) and attached decks excluded from it. <b>It does not consume
                    the 110%.</b> AB 462 (Oct 2025) killed Coastal Commission appeal authority
                    over local ADU CDPs and imposed a 60-day clock. Most underrated lever
                    available.<br><br>
                    <b>Realistic ceiling: ~{rp['total_if_granted']:,} sf across TWO units.</b><br>
                    {rp['tdsf']['note']}
                    {'<br><b style="color:#7a2518">TDSF BINDS BEFORE THE REBUILD RULE — this program busts the cap by ' + format(rp['total_if_granted'] - rp['tdsf']['cap'], ',') + ' sf.</b>' if rp['tdsf_binds'] else ''}
                    <br><br>
                    <span class="cite">{rp['note']}<br><br>
                    That is a well-located small house with a guest unit. It is not the thing
                    that trades against Malibu beachfront comps. If the model needs a single
                    integrated 2,700+ sf luxury envelope, the exemption path does not produce
                    it. The lot may still work — as a small-house thesis, priced against
                    small-house comps, underwritten on speed and land basis. That's a real
                    strategy. It's a different strategy.</span>
                    </div>""", unsafe_allow_html=True)

                    st.markdown(f'<div class="card card-note">{pf1_check()}</div>',
                                unsafe_allow_html=True)

                    with st.expander("What you inherit as a purchaser — diligence, not model inputs",
                                     expanded=False):
                        st.markdown('<span class="cite">The rebuild relief goes with the land. '
                                    'Malibu\'s own rebuild FAQ says the in-kind rights "go with '
                                    'the land" and a new owner can use the expedited processes and '
                                    'CDP exemptions provided the deadlines are met. The legislative '
                                    'record confirms it: <b>SB 1229 (Allen) would limit the CDP '
                                    'exemption to the owner of record immediately preceding the '
                                    'disaster</b> — you cannot close a loophole that does not exist. '
                                    'Allen has said it is prospective and would not apply to the 2025 '
                                    'fires. Track it to the Assembly floor anyway.<br><br>'
                                    'But these attach to the PROPERTY and land on the buyer. None are '
                                    'in the parcel record.</span>', unsafe_allow_html=True)
                        st.write("")
                        for f in purchaser_diligence(p):
                            st.markdown(f'<div class="card card-note">{f}</div>',
                                        unsafe_allow_html=True)

                    if not prior_override:
                        rows_s = ceiling_sensitivity(p.prior_sqft, proposed_ceiling, basement)
                        body = "".join(
                            f"<tr><td style='padding:2px 14px 2px 0'>{r['prior_ceiling']}ft</td>"
                            f"<td style='padding:2px 14px 2px 0'><b>{r['gross']:,}</b> sf</td>"
                            f"<td style='padding:2px 14px 2px 0'>{r['delta']:+.0%}</td>"
                            f"<td style='padding:2px 0'>{r['binding']}</td></tr>"
                            for r in rows_s)
                        lo = min(r["gross"] for r in rows_s)
                        hi = max(r["gross"] for r in rows_s)
                        st.markdown(f"""<div class="card mono" style="font-size:0.75rem">
                        <b>HOW MUCH IS THE GUESS CARRYING?</b><br>
                        <span class="cite">The prior ceiling above is UNSOURCED. Across the
                        plausible range this lot's envelope spans <b>{lo:,}–{hi:,} sf</b>
                        ({(hi/lo - 1):.0%} swing). That is the tool's headline number moving on
                        an assumption nobody sourced.</span><br><br>
                        <table>{body}</table><br>
                        <span class="cite">Kill it: the pre-fire sale listing usually states
                        ceiling height. Enter it above and this table disappears.</span>
                        </div>""", unsafe_allow_html=True)

with tab_batch:
    up = st.file_uploader("Redfin CSV", type=["csv"], label_visibility="collapsed")
    st.markdown('<span class="cite">Redfin search results → Download → drop the file here. '
                'One county lookup per row, so a long export takes a minute.</span>',
                unsafe_allow_html=True)

    if up is not None:
        raw = pd.read_csv(up)
        raw.columns = [c.strip().upper() for c in raw.columns]
        addr_col = next((c for c in raw.columns if "ADDRESS" in c), None)
        if not addr_col:
            st.error("No ADDRESS column in that file. Redfin exports have one — "
                     "check you downloaded the search results rather than a single listing.")
            st.stop()

        st.markdown(f"**{len(raw)} listings.** Checking each against the county record.")
        prog = st.progress(0.0)
        rows = []
        for i, r in raw.iterrows():
            addr = r[addr_col]
            # No MALIBU fallback. A missing CITY column means query unfiltered and
            # let the returned SitusCity decide — never assume a jurisdiction.
            city = r.get("CITY")
            if pd.isna(city):
                city = None
            p = lookup(addr, city)
            listing_sqft = r.get("SQUARE FEET")
            # Redfin exports don't carry storey count. LA rows stay REVIEW without an
            # indicative bracket — check the pre-fire listing per address in the other tab.
            t = triage(p, listing_sqft=listing_sqft)
            env = None
            env_aor = None
            if t.verdict == "ELIGIBLE" and t.jurisdiction == jur.MALIBU and p.prior_sqft:
                ph, _ = ceiling_from_year(p.year_built, prior_override or None)
                if ph:
                    _both = envelope_both_cases(p.prior_sqft, ph, proposed_ceiling, basement)
                    env_aor = _both["as_of_right"]
                    env = _both["if_granted"]
            rows.append(dict(
                Address=addr,
                Verdict=t.verdict,
                Jurisdiction=jur.route(p.situs_city).name if p.found else "—",
                Prior_sf=p.prior_sqft,
                Lot_sf=p.lot_sqft,
                Built=p.year_built,
                Units=p.units,
                As_of_right_sf=env_aor["habitable"] if env_aor else None,
                If_granted_sf=env["habitable"] if env else None,
                Binding=env["binding"] if env else None,
                Delta=f'{env["haircut_vs_prior"]:+.0%}' if env else None,
                Ask=r.get("PRICE"),
                Why=t.reason,
                Rule=t.rule,
            ))
            prog.progress((i + 1) / len(raw))
        prog.empty()

        df = pd.DataFrame(rows)
        order = {"ELIGIBLE": 0, "SCOREABLE": 1, "REVIEW": 2, "UNSCOREABLE": 3, "EXCLUDED": 4}
        df = df.sort_values("Verdict", key=lambda s: s.map(order))

        n_e = (df.Verdict == "ELIGIBLE").sum()
        n_r = (df.Verdict == "REVIEW").sum()
        st.markdown(f"### {n_e} scoreable · {n_r} City of LA (different rulebook) · "
                    f"{len(df) - n_e - n_r} out")

        for v in ["ELIGIBLE", "SCOREABLE", "REVIEW", "UNSCOREABLE", "EXCLUDED"]:
            sub = df[df.Verdict == v]
            if not len(sub):
                continue
            st.markdown(f'{stamp(v)} &nbsp; <span class="cite">{len(sub)}</span>',
                        unsafe_allow_html=True)
            for _, x in sub.iterrows():
                bits = []
                if pd.notna(x.Prior_sf):
                    bits.append(f"{int(x.Prior_sf):,} sf burned")
                if pd.notna(x.As_of_right_sf):
                    bits.append(f"<b>{int(x.As_of_right_sf):,} sf as of right</b>")
                if pd.notna(x.If_granted_sf):
                    bits.append(f"{int(x.If_granted_sf):,} if +10% granted")
                if pd.notna(x.Ask):
                    bits.append(f"${x.Ask:,.0f}")
                why = str(x.Why)
                why = re.sub(r"<[^>]+>", "", why)
                st.markdown(
                    f'<div class="ledger-row">{x.Address} &nbsp;·&nbsp; '
                    f'<span class="cite">{x.Jurisdiction}</span> &nbsp;·&nbsp; '
                    f'{" · ".join(bits) if bits else ""}<br>'
                    f'<span class="cite">{why[:180]}{" · " + x.Rule if x.Rule else ""}</span></div>',
                    unsafe_allow_html=True)
            st.write("")

        buf = io.StringIO()
        df.to_csv(buf, index=False)
        st.download_button("Download the screen", buf.getvalue(),
                           "malibu_screen.csv", "text/csv")

st.markdown("---")
with st.expander("What this tool does and doesn't know", expanded=False):
    st.markdown("""
#### The two rulebooks

**Malibu — Interpretation No. 24** (adopted 15 Oct 2025)
Caps bulk (volume), square footage, **and** height, each at 110% of the prior structure.
Three ceilings, all binding at once (Issue No. 1). Basements and subterranean garages count
against the same 110% (Issue No. 5). Multifamily prior use triggers No Net Loss (Issue No. 8).

**The +10% is discretionary.** Two instruments, two characters: the CDP exemption
(LIP 13.4.6) is criteria-based — meet three tests, no permit, no discretion. The zoning +10%
(MMC 17.60.020(C) / Ordinance 524) is granted *"at the discretion of the planning director."*
The tool shows both: as-of-right, and if-granted. Model the first.

**Breaking the 10% cap on beachfront is a cliff, not a slope.** The LIP's "New Development"
exclusion is conditional and the cap is the condition. Exceed it and you become new development
for PRC 30212 — which requires public access from the nearest public roadway to the shoreline.
The Commission applied exactly this in Malibu in 2011. Armoring flips too: replacement
structures get a seawall via director-level permit; new development runs into the LCP policy
that development requiring armoring should be prohibited. So it isn't "small house quickly or
large house slowly" — on beachfront it's "large house, maybe, with conditions that may destroy
the reason you wanted it large."

**Interpretation No. 24 is not certified LCP text.** Ordinance 524 went to the Coastal
Commission and was certified 10 Apr 2025 as a minor amendment. Interpretation No. 24 was
adopted by City Council alone and was not. Where the LCP and a City resolution conflict, the
LCP takes precedence. Issue No. 10's reasoning — using a public-access carve-out, whose own
precondition is zoning conformity, to establish exemption *from* zoning — is the weakest link,
and beachfront Malibu sits largely in the Commission's appeal jurisdiction.

**SB 1229 (Allen)** would limit the CDP exemption to the owner of record immediately before
the disaster. Passed the Senate 29–9 on 19 May 2026; awaiting an Assembly floor vote. Allen
has said it is prospective and would not apply to the 2025 fires. Its existence is the best
evidence that a purchaser stands in the pre-fire owner's shoes *today*.

**City of Los Angeles — EO1 / EO8**
Caps footprint and height at 110%. **Not** volume, **not** gross square footage. A new storey
is permitted within those caps. EO8 lets zoning-compliant, non-like-for-like single-family
projects bypass local Coastal Act and CEQA review.

LA parcels return REVIEW rather than an envelope: EO1 needs prior **footprint** and the
Assessor publishes gross square footage. The rule is known; the input isn't. So the tool
names the gap instead of guessing across it.
""")
    st.markdown("---")
    st.markdown("""
#### Where each number comes from

| | |
|---|---|
| **Parcel record** | LA County Assessor, live — a *source*, not a verified envelope |
| **Prior ceiling height** | **ESTIMATED, UNSOURCED** unless you override it |
| **Storey count (LA)** | ESTIMATED from the pre-fire listing |
| **What you'd build** | Yours |

The year→height mapping was chosen for plausibility, not taken from any record — and it
drives the volume ceiling, which is this tool's headline finding. On a 989 sf lot the
envelope swings between 870 and 1,088 sf across the plausible range. The sensitivity table
shows how much that guess is carrying. The pre-fire sale listing usually states ceiling
height; enter it and the guess goes away.

**And the baseline itself isn't a survey.** The Assessor is a taxation body — it doesn't
adjudicate permits, and Issue No. 4 lists it as one of five non-exhaustive evidence types.
Issue No. 12 hard-requires a survey at Planning Verification *precisely because* the Assessor
and the plans disagree. Every envelope here inherits whatever error is in that one number.
An empty square-footage field is a blank cell, not a vacancy finding — the diagnostic is
improvement value on the roll, not the sf field.
""")
    st.markdown("---")
    st.markdown("""
#### Not modelled — read before trusting a number

- **The 110% height cap.** Only bulk and square footage are computed. A design can pass here and fail on height.
- **Issue No. 7's ≤10ft-apart test.** Multiple structures are summed and flagged, not combined per the rule.
- **Setbacks, FAR, zoning compliance.** Only the 18ft SPR trigger is checked.
- ~~Whether SPR is appealable~~ — **answered, and it's worse than "appealable."** MMC 17.62.040(E) → 17.04.220: Director → Planning Commission → City Council, both rungs. And *"An action of the planning manager/director appealed to the planning commission shall not become effective unless and until final action by the planning commission."* The appeal **suspends the approval by operation of the code**. Any neighbour suspends your SPR with a filing fee. Design out of SPR — that's not optimization, it's declining to hand five neighbours a suspension switch.
- **Cycle times.** No reliable post-fire Malibu SPR or planning-verification data exists. Any month figure here is an estimate.

**On the things this tool won't estimate.** There's no published grant rate for the discretionary
+10%, and no dedication probability. That's right about *rates* and wrong about *evidence* — the
difference is labour. Malibu has acted on roughly two dozen planning verifications since January
2025: unscoreable as a sample, completely readable as a census. A PRA request reads all 22 and
answers the real question — *has the Planning Director ever exercised that discretion adversely,
and on what facts?* Same for the dedication: decades of Malibu beachfront CDP staff reports are
searchable at documents.coastal.ca.gov. Nobody has run either, because the record is fourteen
months old and the brokers are moving faster than the analysis.

And even after reading all 22 you won't have a probability. So the discipline isn't better
estimation — it's structures that don't need the estimate. Base case at 100%. Design out of the
exaction rather than pricing it. Option the lot you can't baseline.
- **Everything after entitlement.** Cost, carry, comps, exit, insurance, coastal engineering, debris, septic, seawall.

This is a screen. It tells you whether a lot is worth an afternoon. It does not underwrite one.
""")
