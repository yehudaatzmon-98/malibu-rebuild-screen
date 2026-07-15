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
import pandas as pd
import streamlit as st

from county import lookup, triage, envelope, ceiling_from_year, split_address

st.set_page_config(page_title="Malibu Rebuild Screen", layout="wide",
                   initial_sidebar_state="collapsed")

# ---------------------------------------------------------------- type & tone
# The subject's world is the municipal record: assessor rolls, parcel maps, a
# numbered interpretation. Typography borrows from that — a condensed grotesk for
# the record-keeping voice, monospace for every figure, because every figure here
# is evidence and should read as transcribed rather than designed.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=Archivo+Narrow:wght@400;600&family=JetBrains+Mono:wght@400;500;700&display=swap');

.stApp { background: #10100e; }
html, body, [class*="css"] { font-family: 'Archivo', system-ui, sans-serif; color: #f0eee9; }
h1,h2,h3,h4 { font-family: 'Archivo', sans-serif !important; letter-spacing:-0.03em; color:#f5f3ee !important; }

.masthead { border-bottom: 2px solid #3a3833; padding-bottom: 14px; margin-bottom: 6px; }
.title { font-family:'Archivo',sans-serif; font-size:2.5rem; font-weight:800; letter-spacing:-0.045em;
         color:#f5f3ee; line-height:1; margin:0; }
.rule-cite { font-family:'JetBrains Mono',monospace; font-size:0.68rem; color:#a8a294;
             letter-spacing:0.06em; text-transform:uppercase; margin-top:8px; }

/* verdicts read as stamps on a form, not badges in an app */
.stamp { font-family:'JetBrains Mono',monospace; font-size:0.7rem; font-weight:700;
         letter-spacing:0.1em; padding:3px 9px; border:1.5px solid; display:inline-block; }
.s-elig  { color:#9fd67a; border-color:#3f6b2a; background:#18220f; }
.s-excl  { color:#e0725f; border-color:#6b2f26; background:#22110f; }
.s-unsc  { color:#d6b45a; border-color:#6b552a; background:#221c0f; }
.s-rev   { color:#7ab8d6; border-color:#2a4f6b; background:#0f1a22; }

.mono { font-family:'JetBrains Mono',monospace; }
.figure { font-family:'JetBrains Mono',monospace; font-size:1.9rem; font-weight:700; color:#f5f3ee; line-height:1; }
.figure-label { font-family:'JetBrains Mono',monospace; font-size:0.7rem; color:#a8a294 !important;
                letter-spacing:0.1em; text-transform:uppercase; }
.binding { font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#e0725f;
           letter-spacing:0.05em; }
.card { background:#1c1b17; border:1px solid #3a3833; padding:16px 18px; margin-bottom:10px;
        color:#f0eee9 !important; font-size:0.92rem; line-height:1.5; }
.card * { color:#f0eee9 !important; }
/* Streamlit wraps markdown in its own styled divs that override ours */
.stMarkdown, .stMarkdown p, [data-testid="stMarkdownContainer"] p { color:#f0eee9 !important; }
.stExpander p, .stExpander label { color:#e4e1da !important; }
.cite, .cite * { font-family:'JetBrains Mono',monospace !important; font-size:0.72rem !important;
        color:#9b9689 !important; letter-spacing:0.04em; line-height:1.5; }
.ledger-row, .ledger-row * { border-bottom:1px solid #33312c; padding:7px 0;
              font-family:'JetBrains Mono',monospace !important; font-size:0.82rem !important;
              color:#f0eee9 !important; line-height:1.6; }
.sourced { color:#9fd67a; font-family:'JetBrains Mono',monospace; font-size:0.6rem; }
.assumed { color:#d6b45a; font-family:'JetBrains Mono',monospace; font-size:0.6rem; }
hr { border-color:#3a3833; }
.stButton>button { font-family:'JetBrains Mono',monospace; font-weight:600; letter-spacing:0.05em;
                   border-radius:0; border:1.5px solid #4a4740; background:#1d1c18; color:#f0eee9; }
.stButton>button:hover { border-color:#9fd67a; color:#9fd67a; }
</style>
""", unsafe_allow_html=True)


def stamp(v):
    cls = {"ELIGIBLE": "s-elig", "EXCLUDED": "s-excl",
           "UNSCOREABLE": "s-unsc", "REVIEW": "s-rev"}.get(v, "s-rev")
    return f'<span class="stamp {cls}">{v}</span>'


# ---------------------------------------------------------------- masthead
st.markdown("""
<div class="masthead">
  <div class="title">Malibu Rebuild Screen</div>
  <div class="rule-cite">LCP &amp; Zoning Code Interpretation No. 24 · Zoning Code No. 15 · adopted 15 Oct 2025
  &nbsp;·&nbsp; parcel data: LA County Assessor, live</div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
Drop in a Redfin export of new listings. Every address is checked against the County
Assessor for what actually burned, screened against the rebuild rule, and returned with
a verdict and the rule that produced it.

**This is not a valuation.** It answers one question: *is this lot worth your afternoon?*
""")

# ---------------------------------------------------------------- what Tal decides
with st.expander("What you'd build  —  these are your calls, not the model's", expanded=False):
    st.markdown('<span class="cite">The rule is fixed. These are not. Every figure below '
                'is yours and travels with the output.</span>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        proposed_ceiling = st.number_input(
            "Ceiling height you'd build (ft)", 8.0, 14.0, 10.0, 0.5,
            help="This is the single biggest lever in the rule. A 1963 beach house has "
                 "~8.5ft ceilings. Build to 10ft and the volume cap bites — you get LESS "
                 "square footage than burned. Build to 8.5ft and you get the full +10%.")
        st.markdown('<span class="assumed">Currently your input · drives the volume ceiling</span>',
                    unsafe_allow_html=True)
    with c2:
        basement = st.number_input(
            "Basement / subterranean garage you'd build (sf)", 0, 5000, 0, 100,
            help="Counts toward the same 110% (Issue No. 5) and returns nothing per "
                 "finished sf. Every foot here comes out of habitable area.")
        st.markdown('<span class="assumed">Envelope tax · Issue No. 5</span>',
                    unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------- input
tab_batch, tab_one = st.tabs(["Screen a Redfin export", "Check one address"])

with tab_one:
    a = st.text_input("Address", placeholder="20610 Pacific Coast Hwy")
    if st.button("Check it") and a:
        with st.spinner("Pulling the county record…"):
            p = lookup(a)
        if not p.found:
            st.markdown(f'{stamp("UNSCOREABLE")}', unsafe_allow_html=True)
            st.markdown(f'<div class="card mono">{p.note}</div>', unsafe_allow_html=True)
        else:
            t = triage(p)
            st.markdown(f'{stamp(t.verdict)}  <span class="cite">{t.rule}</span>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="card">{t.reason}</div>', unsafe_allow_html=True)
            if t.verdict == "ELIGIBLE" and p.prior_sqft:
                ph, basis = ceiling_from_year(p.year_built)
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
                    <span class="cite">prior ceiling {basis}</span>
                    </div>""", unsafe_allow_html=True)

with tab_batch:
    up = st.file_uploader("Redfin CSV", type=["csv"], label_visibility="collapsed")
    st.markdown('<span class="cite">Redfin search results → Download → drop the file here</span>',
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
            city = r.get("CITY", "MALIBU")
            p = lookup(addr, city)
            listing_sqft = r.get("SQUARE FEET")
            t = triage(p, listing_sqft=listing_sqft)
            env = None
            if t.verdict == "ELIGIBLE" and p.prior_sqft:
                ph, _ = ceiling_from_year(p.year_built)
                if ph:
                    env = envelope(p.prior_sqft, ph, proposed_ceiling, basement)
            rows.append(dict(
                Address=addr,
                Verdict=t.verdict,
                Prior_sf=p.prior_sqft,
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
        st.markdown(f"### {n_e} worth your afternoon · {len(df) - n_e} not")

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
                st.markdown(
                    f'<div class="ledger-row">{x.Address} &nbsp;·&nbsp; '
                    f'{" · ".join(bits) if bits else ""}<br>'
                    f'<span class="cite">{x.Why[:150]}{" · " + x.Rule if x.Rule else ""}</span></div>',
                    unsafe_allow_html=True)
            st.write("")

        buf = io.StringIO()
        df.to_csv(buf, index=False)
        st.download_button("Download the screen", buf.getvalue(),
                           "malibu_screen.csv", "text/csv")

st.markdown("---")
st.markdown("""<span class="cite">
The rule is fixed and cited: 110% of bulk, square footage, OR height — three ceilings,
all binding at once (Issue No. 1). Basements count (Issue No. 5). Multifamily prior use
triggers No Net Loss (Issue No. 8). Assessor-vs-listing conflicts require a survey at
Planning Verification (Issue No. 12). County data is SOURCED. Ceiling height is ESTIMATED
from year built. What you'd build is yours.
</span>""", unsafe_allow_html=True)
