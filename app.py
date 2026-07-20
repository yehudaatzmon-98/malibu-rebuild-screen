"""
Lot Analyzer — the batch funnel.
================================

Michael's tool. Drop in a Redfin export, get a ranked list: eligibility, buildable
envelope, and the money case, in one pass, jurisdiction-correct.

This is the "will it make money" half fused to the screener's "can I build it"
half. The screener already decides eligibility and envelope per lot; this runs that
over a whole CSV and adds the pro forma on top.

Shares the screener's visual identity — municipal record, ink on paper — because
they're one product.

Run:  streamlit run app.py
"""
import io
import pandas as pd
import streamlit as st

import county
import jurisdiction as jur
from county import (Parcel, triage, envelope_both_cases, ceiling_from_year,
                    entitlement_status, thesis_fit)
from engine import (Assumptions, CompMarket, ProForma, sensitivity,
                    what_youd_have_to_believe, discount_to_breakeven)
from diligence import build_card, card_to_rows

st.set_page_config(page_title="Lot Analyzer", layout="wide",
                   initial_sidebar_state="expanded")

# ---- shared identity with the screener: municipal record, ink on paper --------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');
:root{--paper:#faf9f6;--paper-2:#f2f0ea;--ink:#16150f;--ink-soft:#55524a;
      --ink-faint:#6b6860;--rule:#ddd9cd;--seal:#7a2518;--ok:#1f5c2e;--warn:#8a5a00;--info:#1b4f6b;}
.stApp{background:var(--paper);}
html,body,[class*="css"],.stMarkdown,.stMarkdown p{font-family:'Inter',system-ui,sans-serif;color:var(--ink)!important;line-height:1.6;}
h1,h2,h3,h4{font-family:'Newsreader',Georgia,serif!important;color:var(--ink)!important;letter-spacing:-0.01em;font-weight:600;}
.masthead{border-bottom:3px double var(--rule);padding-bottom:14px;margin-bottom:18px;}
.title{font-family:'Newsreader',Georgia,serif;font-size:2.7rem;font-weight:700;letter-spacing:-0.02em;line-height:1.05;margin:0 0 8px;}
.rule-cite{font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:var(--ink-faint);line-height:1.7;}
.stamp{font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700;letter-spacing:0.12em;padding:4px 10px;border:2px solid;display:inline-block;text-transform:uppercase;}
.s-strong{color:var(--ok);border-color:var(--ok);}
.s-buy{color:var(--info);border-color:var(--info);}
.s-maybe{color:var(--warn);border-color:var(--warn);}
.s-pass{color:var(--seal);border-color:var(--seal);}
.s-none{color:var(--ink-faint);border-color:var(--ink-faint);}
.mono{font-family:'JetBrains Mono',monospace;}
.card{background:#fff;border:1px solid var(--rule);border-left:3px solid var(--ink);padding:16px 18px;margin-bottom:10px;}
.card *{color:var(--ink)!important;}
.card-strong{border-left-color:var(--ok);}
.card-pass{border-left-color:var(--seal);}
.card-none{border-left-color:var(--ink-faint);background:var(--paper-2);}
.cite,.cite *{font-family:'Inter',sans-serif!important;font-size:0.82rem!important;color:var(--ink-soft)!important;}
.big{font-family:'JetBrains Mono',monospace;font-size:1.5rem;font-weight:700;}
.lbl{font-family:'Inter',sans-serif;font-size:0.68rem;color:var(--ink-faint)!important;letter-spacing:0.09em;text-transform:uppercase;font-weight:600;}
.stButton>button,.stDownloadButton>button,.stButton>button *,.stDownloadButton>button *{font-family:'Inter'!important;font-weight:600!important;color:var(--paper)!important;}
.stButton>button,.stDownloadButton>button{background:var(--ink);border:1.5px solid var(--ink);border-radius:2px;}
hr{border:none;border-top:1px solid var(--rule);margin:20px 0;}
[data-baseweb="tooltip"],[data-baseweb="tooltip"] *{background:var(--ink)!important;color:var(--paper)!important;}
</style>
""", unsafe_allow_html=True)


def sig_stamp(s):
    cls = {"STRONG":"s-strong","BUY":"s-buy","MAYBE":"s-maybe","PASS":"s-pass"}.get(s,"s-none")
    return f'<span class="stamp {cls}">{s}</span>'


# ---- sidebar: the versioned yardstick -----------------------------------------
st.sidebar.markdown("### The yardstick")
st.sidebar.caption("Fixed assumptions. Move one and every lot re-scores together.")
a = Assumptions(
    construction_psf=st.sidebar.number_input("Construction $/sqft (fully loaded)", 400, 2000, 1000, 50),
    contingency_pct=st.sidebar.slider("Contingency", 0.0, 0.20, 0.08, 0.01),
    carrying_rate=st.sidebar.slider("Carrying rate /yr", 0.0, 0.10, 0.03, 0.005),
    selling_cost_pct=st.sidebar.slider("Selling cost", 0.0, 0.10, 0.05, 0.005),
    appreciation_pct=st.sidebar.slider("Appreciation /yr", -0.05, 0.10, 0.03, 0.005),
    new_build_premium=st.sidebar.slider("New-build premium", 0.0, 0.30, 0.10, 0.01),
)
st.sidebar.markdown(f'<span class="cite">{a.stamp()}</span>', unsafe_allow_html=True)

st.sidebar.markdown("### Negotiation scenario")
st.sidebar.caption("Off by default. The ranking above is priced at full asking — the "
                   "conservative floor. Slide this to see who survives a typical discount, "
                   "as a scenario, not the default.")
discount = st.sidebar.slider("Assume % off asking", 0, 30, 0, 1) / 100.0
if discount > 0:
    st.sidebar.markdown(f'<span class="cite">Scenario: every lot priced at '
                        f'<b>{discount:.0%} below ask</b>. This is a what-if, not a '
                        f'negotiated price.</span>', unsafe_allow_html=True)

# ---- masthead -----------------------------------------------------------------
st.markdown("""
<div class="masthead">
  <div class="title">Lot Analyzer</div>
  <div class="rule-cite">
  Palisades &amp; Malibu development underwriting &nbsp;·&nbsp; eligibility → envelope → money → rank<br>
  comps: 263 Palisades sold sales, 2023-2026 &nbsp;·&nbsp; Malibu returns NO BASIS until comps supplied
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
Drop in a Redfin export. Each lot runs the full funnel: is it eligible to build, how
big an envelope, and does the money work — jurisdiction-correct, never blending
Malibu and Palisades comps. Ranked best to worst, with the full arithmetic behind
every number.

**Not a valuation.** The comps don't reconcile tightly, so each lot shows a range and
what you'd have to believe — a sort order and a decision scaffold, not a green light.
""")


@st.cache_data
def load_comps():
    return pd.read_csv("comps_database.csv")


mkt = CompMarket(load_comps())

up = st.file_uploader("Redfin CSV", type=["csv"])
st.markdown('<span class="cite">Redfin search results → Download. Add a PRIOR_SQFT '
            'column if you have it — it turns the envelope from estimated into sourced.</span>',
            unsafe_allow_html=True)

if up is None:
    st.stop()

raw = pd.read_csv(up)
raw.columns = [c.strip().upper() for c in raw.columns]
addr_col = next((c for c in raw.columns if "ADDRESS" in c), None)
if not addr_col:
    st.error("No ADDRESS column. Download the Redfin search results, not a single listing.")
    st.stop()

st.markdown(f"**{len(raw)} listings.** Running the funnel.")
prog = st.progress(0.0)
results = []

for i, r in raw.iterrows():
    addr = str(r[addr_col])
    city = r.get("CITY")
    price = r.get("PRICE")
    prior = r.get("PRIOR_SQFT")
    lat, lon = r.get("LATITUDE"), r.get("LONGITUDE")
    ptype = str(r.get("PROPERTY TYPE", "")).lower()

    # classify: skip standing houses / condos, keep vacant/land
    is_land = ("land" in ptype or "lot" in ptype or
               (pd.isna(r.get("SQUARE FEET")) and pd.isna(r.get("BEDS"))))

    p = county.lookup(addr, None if pd.isna(city) else city)
    if not p.found and prior and not pd.isna(prior):
        # fall back to the CSV's prior sqft if county missed
        p = Parcel(found=True, situs=addr, situs_city=(None if pd.isna(city) else str(city)),
                   prior_sqft=int(prior), year_built=1960, units=1, use_code="0101")

    j = jur.route(p.situs_city if p.found else (None if pd.isna(city) else str(city)))
    row = dict(Address=addr, Jurisdiction=j.name, Price=price)

    if not p.found:
        row.update(Eligible="UNSCOREABLE", Buildable=None, Signal="NO DATA",
                   ROC=None, Why="No county record and no PRIOR_SQFT supplied.")
        results.append(row); prog.progress((i+1)/len(raw)); continue

    t = triage(p)
    ent = entitlement_status("NONE")  # batch can't know plans; single-lot view handles APPROVED

    # buildable envelope
    build = None
    build_basis = ""
    upside = None
    if j.code == "MALIBU" and p.prior_sqft:
        ph, _ = ceiling_from_year(p.year_built)
        if ph:
            build = envelope_both_cases(p.prior_sqft, ph, 10.0)["as_of_right"]["habitable"]
            build_basis = "as-of-right rebuild"
    elif j.code == "CITY_OF_LA" and p.prior_sqft:
        est = jur.la_envelope_estimate(p.prior_sqft, lot_sqft=p.lot_sqft)
        build = est["base"]
        upside = est.get("upside")
        build_basis = "EO1 base (rebuild same massing)"

    # money
    signal, roc, why = "—", None, t.reason[:120]
    matched = None
    # the asking price is the land cost. A missing or junk price can't be treated
    # as 0 — that makes land free and floats a fake STRONG BUY to the top of the
    # batch. Abstain loudly instead.
    price_ok = (not pd.isna(price)) and float(price) > 1000
    if build and not price_ok:
        signal = "NEED PRICE"
        why = ("No usable asking price in the CSV row. Envelope is "
               f"{build:,.0f} sf — buildable, but the return needs a land cost. "
               "Redfin's PRICE column is usually there; check this row.")
    elif build:
        m = mkt.match(j.code, build, lat if not pd.isna(lat) else None,
                      lon if not pd.isna(lon) else None)
        matched = m.get("comps")
        if m["basis"]:
            express = (j.code == "MALIBU")
            # scenario: apply the sidebar discount to the land cost (ask). At 0 it's ask.
            land = float(price) * (1 - discount)
            pf = ProForma(build, land,
                          m["basis"], j.code, a, express=express,
                          comp_low=m["low"], comp_high=m["high"])
            rr = pf.run()
            if rr["priceable"]:
                signal = rr["signal"]; roc = rr["base"]["roc"]
                # the walk-away number: discount needed to clear 20% ROC, at full ask
                pf_ask = ProForma(build, float(price), m["basis"], j.code, a,
                                  express=express, comp_low=m["low"], comp_high=m["high"])
                dtb = discount_to_breakeven(pf_ask)
                row["_breakeven"] = dtb.get("verdict", "")
                up = f" · +storey upside ~{upside:,.0f} sf" if upside else ""
                scen = f" · scenario −{discount:.0%}" if discount else ""
                why = (f"{build:,.0f} sf ({build_basis}){up} @ ${m['basis']:,}/sf comp basis "
                       f"(range {rr['low']['roc']:.0%}–{rr['high']['roc']:.0%}){scen}. "
                       f"{dtb.get('verdict','')}")
        else:
            signal = "NO COMPS"; why = m["note"]
    elif j.code == "CITY_OF_LA":
        signal = "NEED PRIOR SF"; why = "City of LA lot with no prior sqft in county or CSV — add PRIOR_SQFT to price it."

    # lot-specific killers the screener surfaced, for the diligence card's item 5
    flags = []
    if p.units and p.units > 1:
        flags.append(f"Prior {p.units} units — 'same use' + separation rules [Issue 7/8]; "
                     f"verify unit count and structure separations.")
    if not p.prior_sqft:
        flags.append("No prior sqft — establish a baseline before pricing; option, don't buy.")

    row.update(Eligible=t.verdict, Buildable=build, Signal=signal, ROC=roc, Why=why)
    row["_card"] = build_card(
        address=addr, jurisdiction=j.code, prior_sqft=p.prior_sqft,
        imp_value=getattr(p, "imp_value", None), is_beachfront=None,
        units=p.units, matched_comps=matched, lot_flags=flags or None,
        breakeven=row.get("_breakeven"))
    results.append(row)
    prog.progress((i+1)/len(raw))

prog.empty()
df = pd.DataFrame(results)

# rank: signal tier, then ROC
tier = {"STRONG":0,"BUY":1,"MAYBE":2,"PASS":3,"NO COMPS":4,"NEED PRICE":5,"NEED PRIOR SF":6,"—":7,"NO DATA":8}
df["_t"] = df.Signal.map(lambda s: tier.get(s, 6))
df = df.sort_values(["_t","ROC"], ascending=[True, False], na_position="last").drop(columns="_t")

n_scored = df.ROC.notna().sum()
st.markdown(f"### {n_scored} priceable · {len(df)-n_scored} eligible but not priceable")
st.caption(f"Yardstick: {a.stamp()}")

for _, x in df.iterrows():
    css = "card"
    if x.Signal == "STRONG": css = "card card-strong"
    elif x.Signal == "PASS": css = "card card-pass"
    elif x.Signal in ("NO COMPS","NEED PRICE","NEED PRIOR SF","NO DATA","—"): css = "card card-none"
    bits = [f"{x.Jurisdiction}"]
    if pd.notna(x.Price): bits.append(f"${x.Price:,.0f} ask")
    if pd.notna(x.Buildable): bits.append(f"{x.Buildable:,.0f} sf buildable")
    if pd.notna(x.ROC): bits.append(f"<b>{x.ROC:.0%} ROC</b>")
    be = x.get("_breakeven")
    if be: bits.append(f'<b>{be}</b>')
    st.markdown(
        f'<div class="{css}">{sig_stamp(x.Signal)} &nbsp; <b>{x.Address}</b><br>'
        f'<span class="cite">{" · ".join(bits)}<br>{x.Why}</span></div>',
        unsafe_allow_html=True)
    # the 30->5 worksheet, per lot, kill-ordered
    card = x.get("_card")
    if isinstance(card, list) and card:
        with st.expander(f"Diligence — what to verify before this makes the short list"):
            for it in card:
                badge = {"KNOWN":"✓ known","VERIFY":"~ verify","FIND":"→ find"}.get(it.status, it.status)
                st.markdown(
                    f'<div class="card"><b>{it.rank}. {it.question}</b> &nbsp;'
                    f'<span class="cite">[{badge}]</span><br>'
                    f'<span class="cite"><b>Have:</b> {it.have}<br>'
                    f'<b>Get it:</b> {it.where}<br>'
                    f'<b>Kills it if:</b> {it.kills_if}</span></div>',
                    unsafe_allow_html=True)

st.markdown("---")
c1, c2 = st.columns(2)
with c1:
    buf = io.StringIO()
    df.drop(columns=[c for c in ["_card"] if c in df.columns]).to_csv(buf, index=False)
    st.download_button("Download the ranked list", buf.getvalue(),
                       "lot_analysis.csv", "text/csv")
with c2:
    # the worksheet: every survivor's card flattened, blank columns for Michael
    rows = []
    for _, x in df.iterrows():
        card = x.get("_card")
        if isinstance(card, list) and card:
            rows.extend(card_to_rows(x.Address, card))
    if rows:
        wbuf = io.StringIO()
        pd.DataFrame(rows).to_csv(wbuf, index=False)
        st.download_button("Download the diligence worksheet", wbuf.getvalue(),
                           "diligence_worksheet.csv", "text/csv",
                           help="One row per check, kill-ordered, with blank columns for "
                                "Michael to fill in and hand back to Tal.")
