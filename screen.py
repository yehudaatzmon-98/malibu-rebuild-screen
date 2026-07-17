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

from county import (lookup, triage, envelope, ceiling_from_year, split_address,
                    ceiling_sensitivity, spr_check)
import jurisdiction as jur

st.set_page_config(page_title="Rebuild Screen", layout="wide",
                   initial_sidebar_state="collapsed")

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
.stButton>button { font-family:'Inter',sans-serif; font-weight:600; letter-spacing:0.02em;
                   border-radius:2px; border:1.5px solid var(--ink); background:var(--ink);
                   color:var(--paper); padding:8px 22px; }
.stButton>button:hover { background:var(--seal); border-color:var(--seal); color:#fff; }
.stButton>button:focus-visible { outline:3px solid var(--info); outline-offset:2px; }

label, .stTextInput label, .stNumberInput label, .stSelectbox label,
[data-testid="stWidgetLabel"] p {
  font-family:'Inter',sans-serif !important; font-size:0.82rem !important;
  font-weight:600 !important; color:var(--ink) !important; letter-spacing:0.01em; }

.stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
  background:#fff !important; color:var(--ink) !important;
  border:1.5px solid var(--rule) !important; border-radius:2px !important;
  font-family:'JetBrains Mono',monospace !important; }
.stTextInput input:focus, .stNumberInput input:focus { border-color:var(--ink) !important; }

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
    cls = {"ELIGIBLE": "s-elig", "EXCLUDED": "s-excl",
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
        storeys_build = st.number_input(
            "Storeys you'd build", 1, 4, 1, 1,
            help="Ceiling height x storeys is checked against the 18ft SPR threshold.")
        st.markdown('<span class="cite">Checked against the 18ft threshold on Malibu '
                    'non-beachfront lots.</span>', unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------- input
tab_batch, tab_one = st.tabs(["Screen a Redfin export", "Check one address"])

with tab_one:
    ca1, ca2, ca3 = st.columns([3, 1, 1])
    with ca1:
        a = st.text_input("Address", placeholder="20610 Pacific Coast Hwy")
    with ca2:
        claimed = st.number_input(
            "Prior sf the listing claims", 0, 50000, 0, 50,
            help="What the listing says burned. The tool compares it to the county record.")
    with ca3:
        storeys_in = st.number_input(
            "Storeys (City of LA only)", 0, 4, 0, 1,
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
            st.markdown(f'{stamp(t.verdict)}  <span class="cite">{j.name}'
                        f'{" · " + t.rule if t.rule else ""}</span>',
                        unsafe_allow_html=True)
            if p.note:
                st.markdown(f'<div class="card mono" style="font-size:0.75rem">{p.note}</div>',
                            unsafe_allow_html=True)
            st.markdown(f'<div class="card">{t.reason}</div>', unsafe_allow_html=True)
            # Envelope math is Interp. No. 24 — Malibu only. Never run it elsewhere.
            if t.verdict == "ELIGIBLE" and t.jurisdiction == jur.MALIBU and p.prior_sqft:
                spr = spr_check(beachfront, proposed_ceiling, storeys_build)
                if spr:
                    st.markdown(f'<div class="card">{spr}</div>', unsafe_allow_html=True)
                ph, basis = ceiling_from_year(p.year_built, prior_override or None)
                if ph:
                    e = envelope(p.prior_sqft, ph, proposed_ceiling, basement)
                    k1, k2, k3 = st.columns(3)
                    with k1:
                        st.markdown(f'<div class="figure-label">what burned</div>'
                                    f'<div class="figure">{p.prior_sqft:,}</div>'
                                    f'<span class="sourced">SOURCED · county</span>',
                                    unsafe_allow_html=True)
                    with k2:
                        st.markdown(f'<div class="figure-label">what you can build</div>'
                                    f'<div class="figure">{e["habitable"]:,}</div>'
                                    f'<span class="binding">{e["haircut_vs_prior"]:+.0%} vs prior</span>',
                                    unsafe_allow_html=True)
                    with k3:
                        st.markdown(f'<div class="figure-label">binding ceiling</div>'
                                    f'<div class="figure" style="font-size:1.1rem;padding-top:12px">'
                                    f'{e["binding"]}</div>', unsafe_allow_html=True)
                    st.markdown(f"""<div class="card mono" style="font-size:0.75rem">
                    sqft ceiling &nbsp; {p.prior_sqft:,} × 1.10 = <b>{e['sqft_cap']:,}</b><br>
                    volume ceiling &nbsp; ({p.prior_sqft:,} × {ph}ft × 1.10) ÷ {proposed_ceiling}ft = <b>{e['vol_cap']:,}</b><br>
                    <span class="binding">→ {e['binding']} binds at {e['gross']:,} sf</span><br>
                    <span class="cite">prior ceiling: {basis}</span>
                    </div>""", unsafe_allow_html=True)

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
            if t.verdict == "ELIGIBLE" and t.jurisdiction == jur.MALIBU and p.prior_sqft:
                ph, _ = ceiling_from_year(p.year_built, prior_override or None)
                if ph:
                    env = envelope(p.prior_sqft, ph, proposed_ceiling, basement)
            rows.append(dict(
                Address=addr,
                Verdict=t.verdict,
                Jurisdiction=jur.route(p.situs_city).name if p.found else "—",
                Prior_sf=p.prior_sqft,
                Lot_sf=p.lot_sqft,
                Built=p.year_built,
                Units=p.units,
                Buildable_sf=env["habitable"] if env else None,
                Binding=env["binding"] if env else None,
                Delta=f'{env["haircut_vs_prior"]:+.0%}' if env else None,
                Ask=r.get("PRICE"),
                Why=t.reason,
                Rule=t.rule,
            ))
            prog.progress((i + 1) / len(raw))
        prog.empty()

        df = pd.DataFrame(rows)
        order = {"ELIGIBLE": 0, "REVIEW": 1, "UNSCOREABLE": 2, "EXCLUDED": 3}
        df = df.sort_values("Verdict", key=lambda s: s.map(order))

        n_e = (df.Verdict == "ELIGIBLE").sum()
        n_r = (df.Verdict == "REVIEW").sum()
        st.markdown(f"### {n_e} scoreable · {n_r} City of LA (different rulebook) · "
                    f"{len(df) - n_e - n_r} out")

        for v in ["ELIGIBLE", "REVIEW", "UNSCOREABLE", "EXCLUDED"]:
            sub = df[df.Verdict == v]
            if not len(sub):
                continue
            st.markdown(f'{stamp(v)} &nbsp; <span class="cite">{len(sub)}</span>',
                        unsafe_allow_html=True)
            for _, x in sub.iterrows():
                bits = []
                if pd.notna(x.Prior_sf):
                    bits.append(f"{int(x.Prior_sf):,} sf burned")
                if pd.notna(x.Buildable_sf):
                    bits.append(f"<b>{int(x.Buildable_sf):,} sf buildable ({x.Delta})</b>")
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
On non-beachfront lots, any increase above 18ft needs Site Plan Review — so the +10% is
discretionary there, not automatic (Issue No. 9).

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
| **Parcel record** | SOURCED — LA County Assessor, live |
| **Prior ceiling height** | **ESTIMATED, UNSOURCED** unless you override it |
| **Storey count (LA)** | ESTIMATED from the pre-fire listing |
| **What you'd build** | Yours |

The year→height mapping was chosen for plausibility, not taken from any record — and it
drives the volume ceiling, which is this tool's headline finding. On a 989 sf lot the
envelope swings between 870 and 1,088 sf across the plausible range. The sensitivity table
shows how much that guess is carrying. The pre-fire sale listing usually states ceiling
height; enter it and the guess goes away.
""")
    st.markdown("---")
    st.markdown("""
#### Not modelled — read before trusting a number

- **The 110% height cap.** Only bulk and square footage are computed. A design can pass here and fail on height.
- **Issue No. 7's ≤10ft-apart test.** Multiple structures are summed and flagged, not combined per the rule.
- **Setbacks, FAR, zoning compliance.** Issue No. 9 requires the +10% to comply with current zoning; only the 18ft height trigger is checked.
- **Everything after entitlement.** Cost, carry, comps, exit, insurance, coastal engineering, debris, septic, seawall.

This is a screen. It tells you whether a lot is worth an afternoon. It does not underwrite one.
""")
