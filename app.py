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
                    what_youd_have_to_believe, discount_to_breakeven, path_to_strong)
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


# Tal's ask: the comp set has to stay current. The bundled file is pre-fire sales; he
# wants to ADD homes selling NOW in nearby non-burned blocks, which are the better read
# on exit pricing. So uploads MERGE by default — replacing would throw away the 263
# sold comps already collected. Dedupe on address + sold date so re-uploading a file
# that overlaps doesn't double-count a sale.
with st.sidebar:
    st.markdown("### Comps")
    comps_up = st.file_uploader("Add more comps (CSV)", type=["csv"],
                                key="comps_upload",
                                help="Same columns as the bundled file: address, city, "
                                     "price, square_feet, price_per_square_foot, sold_date, "
                                     "latitude, longitude.")
    comps_mode = st.radio("How to use them", ["Add to the existing comps", "Replace them"],
                          index=0, key="comps_mode",
                          help="Add is almost always right — more recent sales make the "
                               "exit estimate better. Replace only if the bundled set is wrong.")

base_comps = load_comps()
if comps_up is not None:
    new_comps = pd.read_csv(comps_up)
    if comps_mode.startswith("Add"):
        before = len(base_comps)
        comps_df = pd.concat([base_comps, new_comps], ignore_index=True)
        # dedupe: same address + same sold date is the same sale
        key_cols = [c for c in ["address", "sold_date"] if c in comps_df.columns]
        if key_cols:
            comps_df = comps_df.drop_duplicates(subset=key_cols, keep="last")
        added = len(comps_df) - before
        comps_sig = f"merge-{len(comps_df)}-{comps_up.name}"
        st.sidebar.success(f"{len(comps_df):,} comps in play — "
                           f"{added:,} new added to the original {before:,}")
    else:
        comps_df = new_comps
        comps_sig = f"replace-{len(comps_df)}-{comps_up.name}"
        st.sidebar.warning(f"Using only your {len(comps_df):,} comps — the bundled "
                           f"{len(base_comps):,} are set aside")
else:
    comps_df = base_comps
    comps_sig = "bundled"
    st.sidebar.caption(f"Using the bundled {len(base_comps):,} sold sales")

mkt = CompMarket(comps_df)

up = st.file_uploader("Redfin CSV", type=["csv"])
st.markdown('<span class="cite">Redfin search results → Download. Add a PRIOR_SQFT '
            'column if you have it — it turns the envelope from estimated into sourced.</span>',
            unsafe_allow_html=True)

# Tal: "I cannot paste an address and check it right now." One-off lookups shouldn't
# require building a CSV first.
with st.expander("Or check a single address"):
    sa1, sa2, sa3 = st.columns([3, 1, 1])
    with sa1:
        one_addr = st.text_input("Address", placeholder="955 Fisk St, Pacific Palisades",
                                 key="one_addr")
    with sa2:
        one_price = st.number_input("Asking price ($)", 0, 100_000_000, 0, 25_000,
                                    key="one_price")
    with sa3:
        one_prior = st.number_input("Prior sqft (optional)", 0, 30_000, 0, 100,
                                    key="one_prior",
                                    help="If you know the real prior house size, enter it "
                                         "— it beats the county record.")
    if st.button("Check it", key="one_go") and one_addr:
        p1 = county.lookup(one_addr, None)
        if one_prior:
            if p1.found:
                p1.prior_sqft = int(one_prior)
            else:
                p1 = Parcel(found=True, situs=one_addr, situs_city=None,
                            prior_sqft=int(one_prior), year_built=1960, units=1,
                            use_code="0101")
        if not p1.found:
            st.warning("No county record found for that address. Enter the prior sqft above "
                       "and try again — that's enough to score it.")
        else:
            j1 = jur.route(p1.situs_city)
            b1 = None
            if j1.code == "MALIBU" and p1.prior_sqft:
                ph1, _ = ceiling_from_year(p1.year_built)
                if ph1:
                    b1 = envelope_both_cases(p1.prior_sqft, ph1, 10.0)["as_of_right"]["habitable"]
            elif p1.prior_sqft:
                b1 = jur.la_envelope_estimate(p1.prior_sqft, lot_sqft=p1.lot_sqft)["base"]
            if not b1:
                st.warning(f"{j1.name}: no prior square footage on record. Enter it above to "
                           f"score this lot.")
            else:
                m1 = mkt.match(j1.code, b1, None, None)
                if not m1.get("basis"):
                    st.info(f"{j1.name} · {b1:,.0f} sf buildable. {m1['note']}")
                elif not one_price:
                    st.info(f"{j1.name} · {b1:,.0f} sf buildable · comps ~${m1['basis']:,}/sf. "
                            f"Enter an asking price for the return.")
                else:
                    pf1 = ProForma(b1, float(one_price), m1["basis"], j1.code, a,
                                   express=(j1.code == "MALIBU"),
                                   comp_low=m1["low"], comp_high=m1["high"])
                    r1 = pf1.run(); bb = r1["base"]
                    d1 = discount_to_breakeven(pf1)
                    st.markdown(
                        f'<div class="card card-strong">{sig_stamp(r1["signal"])} &nbsp; '
                        f'<b>{one_addr}</b><br><span class="cite">'
                        f'{j1.name} · ${one_price:,.0f} ask · {b1:,.0f} sf buildable · '
                        f'<b>{bb["roc"]:.0%} ROC</b> · {d1.get("verdict","")}<br>'
                        f'total cost ${bb["total_cost"]:,.0f} · net sale '
                        f'${bb["net_sale"]:,.0f} · profit <b>${bb["profit"]:,.0f}</b>'
                        f'</span></div>', unsafe_allow_html=True)

# first-run: teach, don't dead-end. Offer sample data so results appear in one click.
use_sample = False
if up is None:
    st.markdown("---")
    colA, colB = st.columns([1, 1])
    with colA:
        st.markdown("""
#### How to use this

**1. Get the data.** On Redfin, search the area (e.g. Pacific Palisades or Malibu),
then on the results page click **Download** (bottom of the list) to save a CSV of
every listing.

**2. Drop it in** the box above. The tool reads Redfin's standard columns — address,
price, lot size, coordinates — automatically. You don't type anything per property.

**3. Read the ranked list.** Every lot comes back sorted best-to-worst with a signal
and the math behind it. Click any lot for the diligence checklist — what to verify
before it's worth a call.

**Want to see it work first?** Load the sample below — three lots, one of each outcome.
        """)
        if st.button("Load sample data →"):
            use_sample = True
    with colB:
        st.markdown("""
#### What the signals mean

**STRONG / BUY** — the return clears the bar at asking price. Worth a call.

**MAYBE** — marginal. Only worth it if the price moves.

**PASS** — loses money at this price.

**NO COMPS** — a Malibu lot. Buildable, but we have no Malibu sales to price it
against yet. Envelope shows; the money waits on Malibu comps.

**NEED PRICE / NEED PRIOR SF** — a data gap in that row, not a verdict. The tool
refuses to guess. Add the missing column and it scores.

<span class="cite">Every number is priced at <b>full asking</b> — the conservative
floor. Each lot also shows the discount it would need to clear the bar, so you know
your walk-away number before you call.</span>
        """, unsafe_allow_html=True)
    if not use_sample:
        st.stop()

if up is not None:
    raw = pd.read_csv(up)
elif use_sample:
    raw = pd.read_csv("sample_redfin_export.csv")
    st.info("Showing sample data — three lots, one of each outcome. "
            "Upload your own Redfin CSV above to replace it.")
else:
    st.stop()
raw.columns = [c.strip().upper() for c in raw.columns]
addr_col = next((c for c in raw.columns if "ADDRESS" in c), None)
if not addr_col:
    st.error("No ADDRESS column. Download the Redfin search results, not a single listing.")
    st.stop()

# Streamlit re-runs the whole script on every widget click. The batch does one live
# county lookup per row, so without caching, moving a slider in the per-lot playground
# would re-run 172 lookups and take a minute. Key the cache on the file contents +
# comp source so a new upload recomputes but widget clicks don't.
_sig = f"{len(raw)}-{hash(tuple(raw[addr_col].astype(str)))}-{comps_sig}"
if st.session_state.get("_batch_sig") != _sig:
    st.session_state["_batch_sig"] = _sig
    st.session_state["_facts"] = None
    st.session_state.setdefault("_overrides", {})
    st.session_state.setdefault("_shortlist", set())

# ---------------------------------------------------------------------------
# PHASE 1 — the expensive part, run ONCE per uploaded file.
# County lookup, envelope, comp match. None of this depends on the assumption
# sliders, so it must not re-run when someone moves one. Streamlit re-runs the
# whole script on every click; without this cache, a slider move would redo 172
# county lookups and take a minute. Facts in, cached; math applied fresh below.
# ---------------------------------------------------------------------------
def _gather_facts(raw, addr_col, mkt):
    facts = []
    prog = st.progress(0.0, text="Checking each address against the county record…")
    n = len(raw)
    for i, r in raw.iterrows():
        addr = str(r[addr_col])
        if not addr or addr.strip().lower() in ("nan", "none", ""):
            prog.progress(min((i + 1) / n, 1.0)); continue
        city = r.get("CITY"); price = r.get("PRICE"); prior = r.get("PRIOR_SQFT")
        lat, lon = r.get("LATITUDE"), r.get("LONGITUDE")

        csv_prior = None
        if prior is not None and not pd.isna(prior):
            try: csv_prior = int(float(prior))
            except (TypeError, ValueError): csv_prior = None

        p = county.lookup(addr, None if pd.isna(city) else city)
        if csv_prior:
            if p.found:
                p.prior_sqft = csv_prior
            else:
                p = Parcel(found=True, situs=addr,
                           situs_city=(None if pd.isna(city) else str(city)),
                           prior_sqft=csv_prior, year_built=1960, units=1, use_code="0101")

        j = jur.route(p.situs_city if p.found else (None if pd.isna(city) else str(city)))
        f = dict(Address=addr, Jurisdiction=j.name, jcode=j.code,
                 Price=(float(price) if (price is not None and not pd.isna(price)) else None),
                 prior_sqft=None, imp_value=None, units=None,
                 Buildable=None, build_basis="", upside=None,
                 comp_basis=None, comp_low=None, comp_high=None, comps=None,
                 express=(j.code == "MALIBU"), status=None, rule_note="", flags=[])

        if not p.found:
            f.update(Eligible="UNSCOREABLE", status="NO DATA",
                     rule_note=("No county match and no PRIOR_SQFT in the CSV. Add a "
                                "PRIOR_SQFT column (from ParcelQuest or the pre-fire "
                                "listing) to score this lot."))
            facts.append(f); prog.progress(min((i + 1) / n, 1.0)); continue

        t = triage(p)
        f.update(Eligible=t.verdict, prior_sqft=p.prior_sqft,
                 imp_value=getattr(p, "imp_value", None), units=p.units,
                 rule_note=t.reason[:120])

        build = None; build_basis = ""; upside = None
        if j.code == "MALIBU" and p.prior_sqft:
            ph, _ = ceiling_from_year(p.year_built)
            if ph:
                build = envelope_both_cases(p.prior_sqft, ph, 10.0)["as_of_right"]["habitable"]
                build_basis = "as-of-right rebuild"
        elif j.code == "CITY_OF_LA" and p.prior_sqft:
            est = jur.la_envelope_estimate(p.prior_sqft, lot_sqft=p.lot_sqft)
            build = est["base"]; upside = est.get("upside")
            build_basis = "EO1 base (rebuild same massing)"
        f.update(Buildable=build, build_basis=build_basis, upside=upside)

        if build:
            m = mkt.match(j.code, build, lat if not pd.isna(lat) else None,
                          lon if not pd.isna(lon) else None)
            f.update(comps=m.get("comps"), comp_basis=m.get("basis"),
                     comp_low=m.get("low"), comp_high=m.get("high"))
            if not m.get("basis"):
                f["status"] = "NO COMPS"; f["rule_note"] = m["note"]
            elif not f["Price"]:
                f["status"] = "NEED PRICE"
        elif j.code == "CITY_OF_LA":
            f["status"] = "NEED PRIOR SF"
            f["rule_note"] = ("City of LA lot with no prior sqft in county or CSV — "
                              "add PRIOR_SQFT to price it.")

        flags = []
        if p.units and p.units > 1:
            flags.append(f"Prior {p.units} units — 'same use' + separation rules "
                         f"[Issue 7/8]; verify unit count and structure separations.")
        if not p.prior_sqft:
            flags.append("No prior sqft — establish a baseline before pricing; option, "
                         "don't buy.")
        f["flags"] = flags
        facts.append(f); prog.progress(min((i + 1) / n, 1.0))
    prog.empty()
    return facts


if st.session_state.get("_facts") is None:
    st.session_state["_facts"] = _gather_facts(raw, addr_col, mkt)

facts = st.session_state["_facts"]
overrides = st.session_state.setdefault("_overrides", {})

# ---------------------------------------------------------------------------
# PHASE 2 — the cheap part. Applies the current sliders AND any per-lot override
# to the cached facts. Re-runs instantly on every click, which is what makes the
# per-lot "what would make this a strong buy" playground usable.
# ---------------------------------------------------------------------------
def _score(f, a_, discount_):
    """Return a display row for one lot under the current assumptions + overrides."""
    o = overrides.get(f["Address"], {})
    build = o.get("build") or f["Buildable"]
    basis = o.get("exit_psf") or f["comp_basis"]
    ask = f["Price"]
    # per-lot offer price wins over the global discount scenario
    if o.get("offer"):
        land = float(o["offer"])
    elif ask:
        land = float(ask) * (1 - discount_)
    else:
        land = None
    a_lot = a_
    if o.get("constr"):
        a_lot = Assumptions(**{**a_.__dict__, "construction_psf": float(o["constr"])})

    row = dict(Address=f["Address"], Jurisdiction=f["Jurisdiction"], Price=ask,
               Buildable=build, Eligible=f.get("Eligible"), ROC=None,
               Signal=f.get("status") or "—", Why=f.get("rule_note", ""),
               _f=f, _override=bool(o))
    # every lot the county found gets a diligence card, priceable or not — a lot that
    # needs a price or Malibu comps still needs its baseline verified.
    if f.get("status") != "NO DATA":
        row["_card"] = build_card(
            address=f["Address"], jurisdiction=f["jcode"], prior_sqft=f["prior_sqft"],
            imp_value=f["imp_value"], is_beachfront=None, units=f["units"],
            matched_comps=f["comps"], lot_flags=f["flags"] or None, breakeven=None)

    if f.get("status") in ("NO DATA", "NO COMPS", "NEED PRIOR SF"):
        return row
    if not build or not basis:
        return row
    if not land:
        row["Signal"] = "NEED PRICE"
        row["Why"] = (f"Envelope is {build:,.0f} sf — buildable, but the return needs a "
                      f"land cost. Add the price, or set an offer in the what-if below.")
        return row

    pf = ProForma(build, land, basis, f["jcode"], a_lot, express=f["express"],
                  comp_low=f["comp_low"], comp_high=f["comp_high"])
    rr = pf.run()
    if not rr.get("priceable"):
        return row
    row["Signal"] = rr["signal"]; row["ROC"] = rr["base"]["roc"]
    row["_pf"] = pf
    dtb = discount_to_breakeven(
        ProForma(build, float(ask), basis, f["jcode"], a_lot, express=f["express"],
                 comp_low=f["comp_low"], comp_high=f["comp_high"])) if ask else {}
    row["_breakeven"] = dtb.get("verdict", "")
    up = f" · +storey upside ~{f['upside']:,.0f} sf" if f.get("upside") else ""
    scen = ""
    if o:
        bits = []
        if o.get("offer"): bits.append(f"offer ${float(o['offer']):,.0f}")
        if o.get("constr"): bits.append(f"build ${float(o['constr']):,.0f}/sf")
        if o.get("build"): bits.append(f"{float(o['build']):,.0f} sf")
        if o.get("exit_psf"): bits.append(f"exit ${float(o['exit_psf']):,.0f}/sf")
        scen = f" · YOUR SCENARIO: {', '.join(bits)}"
    elif discount_:
        scen = f" · scenario −{discount_:.0%}"
    row["Why"] = (f"{build:,.0f} sf ({f['build_basis']}){up} @ ${basis:,.0f}/sf comp basis "
                  f"(range {rr['low']['roc']:.0%}–{rr['high']['roc']:.0%}){scen}. "
                  f"{row['_breakeven']}")
    # rebuild the card now that we know the walk-away number, so step 4 carries it
    row["_card"] = build_card(
        address=f["Address"], jurisdiction=f["jcode"], prior_sqft=f["prior_sqft"],
        imp_value=f["imp_value"], is_beachfront=None, units=f["units"],
        matched_comps=f["comps"], lot_flags=f["flags"] or None,
        breakeven=row.get("_breakeven"))
    return row


df = pd.DataFrame([_score(f, a, discount) for f in facts])
tier = {"STRONG":0,"BUY":1,"MAYBE":2,"PASS":3,"NO COMPS":4,"NEED PRICE":5,
        "NEED PRIOR SF":6,"—":7,"NO DATA":8}
df["_t"] = df.Signal.map(lambda s: tier.get(s, 7))
df = df.sort_values(["_t","ROC"], ascending=[True, False], na_position="last").drop(columns="_t")

n_scored = df.ROC.notna().sum()
st.markdown("---")
st.markdown(f"### Results — {len(df)} lots, best to worst")
st.markdown(f'<span class="cite">{n_scored} priceable · {len(df)-n_scored} eligible but '
            f'not yet priceable (a data gap, not a rejection).</span>',
            unsafe_allow_html=True)
st.caption(f"Priced at full asking · yardstick: {a.stamp()}")

with st.expander("What to do with this list  →  read me first", expanded=True):
    st.markdown("""
**The list is sorted by profit — the best opportunities are at the top.** Here's how to
turn it into a short list of lots worth pursuing:

**Step 1 — Start at the top.** The STRONG and BUY lots clear the return bar at the
current asking price. Those are the ones worth acting on. MAYBE is marginal; PASS
loses money — you can ignore those for now.

**Step 2 — Open each top lot's diligence checklist** (click *"Diligence — what to
verify"* under any lot). It lists the 4–5 things to confirm before the lot is real,
in order of what's most likely to kill the deal — starting with "is the prior square
footage real" and ending with "call the agent." Each item says exactly where to get
the answer.

**Step 3 — Note the walk-away number.** Every lot shows the discount it needs to clear
the bar (e.g. *"clears 20% at full asking, room to overpay 83%"*). That's the number
to hold in your head before you call — if the seller won't get near it, move on.

**Step 4 — Download the worksheet** (button at the very bottom). It's the whole short
list as a checklist, with blank columns to fill in as you make calls and pull records.
This is the sheet to hand to whoever is doing the legwork.

**Step 5 — Report back.** The lots that survive the checklist — prior sqft confirmed,
seller willing to deal, no hidden killer — are the ones that go to the partners for a
real look. That's how ~130 becomes the 5 worth an offer.
    """)

shortlist = st.session_state.setdefault("_shortlist", set())

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

    # Tal: "I find a property I like. How do I export it? I don't want to write it down."
    keep_col, card_col = st.columns([1, 22])
    with keep_col:
        keep = st.checkbox("★", key=f"keep_{x.Address}",
                           value=(x.Address in shortlist),
                           label_visibility="collapsed",
                           help="Save to your short list")
    if keep:
        shortlist.add(x.Address)
    else:
        shortlist.discard(x.Address)
    with card_col:
        st.markdown(
            f'<div class="{css}">{sig_stamp(x.Signal)} &nbsp; <b>{x.Address}</b><br>'
            f'<span class="cite">{" · ".join(bits)}<br>{x.Why}</span></div>',
            unsafe_allow_html=True)

        # ---- "what would make this a STRONG buy?" — solved, not guessed ----
        pf_row = x.get("_pf")
        if pf_row is not None and x.Signal in ("BUY", "MAYBE", "PASS"):
            pts = path_to_strong(pf_row)
            if pts.get("ok") and not pts.get("already"):
                reach = [L for L in pts["levers"] if L.get("reachable")]
                miss = [L for L in pts["levers"] if not L.get("reachable")]
                head = (f"What would make this a STRONG buy? "
                        f"(now {pts['current_roc']:.0%}, needs {pts['target_roc']:.0%})")
                with st.expander(head):
                    if reach:
                        st.markdown('<span class="cite">Any <b>one</b> of these on its own '
                                    'gets you there — everything else held as-is:</span>',
                                    unsafe_allow_html=True)
                        for L in reach:
                            st.markdown(
                                f'<div class="card"><b>{L["label"]}</b> — '
                                f'<span class="cite">{L["phrase"]}</span></div>',
                                unsafe_allow_html=True)
                        st.markdown('<span class="cite">Combining two gets there with less '
                                    'of each. Use the <b>What if…</b> panel above to try a '
                                    'mix and see where it lands.</span>',
                                    unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="cite">No single change gets this to STRONG. '
                                    'It would take a combination — or the lot just isn\'t '
                                    'one.</span>', unsafe_allow_html=True)
                    if miss:
                        st.markdown('<span class="cite">Won\'t do it alone: ' +
                                    "; ".join(L["phrase"] for L in miss) + '</span>',
                                    unsafe_allow_html=True)

        # ---- Tal's main ask: play with THIS lot until it's a strong buy ----
        f = x.get("_f") or {}
        if f.get("comp_basis") and f.get("Buildable"):
            o = overrides.get(x.Address, {})
            with st.expander("What if… — change this lot's numbers and watch the signal move"):
                st.markdown('<span class="cite">Everything here affects <b>this lot only</b>. '
                            'Leave a box at its default to keep the standard assumption. '
                            'The signal above updates as soon as you change something.</span>',
                            unsafe_allow_html=True)
                w1, w2 = st.columns(2)
                with w1:
                    offer = st.number_input(
                        "Your offer price ($)", 0, 100_000_000,
                        int(o.get("offer") or (f.get("Price") or 0)), 25_000,
                        key=f"off_{x.Address}",
                        help="What you'd actually pay. The list prices at full asking; "
                             "drop this to see what a negotiated price does.")
                    constr = st.number_input(
                        "Construction $/sqft", 300, 2500,
                        int(o.get("constr") or a.construction_psf), 25,
                        key=f"con_{x.Address}",
                        help="A simple flat lot with good access builds cheaper than a "
                             "hillside. Default is the sidebar number.")
                with w2:
                    bld = st.number_input(
                        "Buildable sqft", 0, 30_000,
                        int(o.get("build") or f.get("Buildable") or 0), 100,
                        key=f"bld_{x.Address}",
                        help="Override if you know the real prior house was bigger — "
                             "e.g. a multi-storey home with a basement the county "
                             "under-recorded.")
                    xpsf = st.number_input(
                        "Exit $/sqft", 0, 12_000,
                        int(o.get("exit_psf") or f.get("comp_basis") or 0), 50,
                        key=f"xps_{x.Address}",
                        help="What the finished home sells for per foot. Default is the "
                             "matched comp basis; override with your own read.")
                b1, b2 = st.columns([1, 1])
                with b1:
                    if st.button("Apply to this lot", key=f"apply_{x.Address}"):
                        nd = {}
                        if offer and offer != (f.get("Price") or 0): nd["offer"] = offer
                        if constr and constr != a.construction_psf: nd["constr"] = constr
                        if bld and bld != f.get("Buildable"): nd["build"] = bld
                        if xpsf and xpsf != f.get("comp_basis"): nd["exit_psf"] = xpsf
                        if nd: overrides[x.Address] = nd
                        else: overrides.pop(x.Address, None)
                        st.rerun()
                with b2:
                    if o and st.button("Reset to defaults", key=f"rst_{x.Address}"):
                        overrides.pop(x.Address, None)
                        st.rerun()
                if o:
                    st.markdown('<span class="cite">★ This lot is running on <b>your</b> '
                                'numbers, not the defaults. It\'s marked in the export.'
                                '</span>', unsafe_allow_html=True)

        # the 30->5 worksheet, per lot, kill-ordered
        card = x.get("_card")
        if isinstance(card, list) and card:
            with st.expander("How to check this lot — work top to bottom, stop if any step fails"):
                st.markdown('<span class="cite">Do the steps in order. Each one is cheap to start '
                            'and the first ones are most likely to kill a bad lot — so a dead lot '
                            'dies fast, before you spend a phone call on it.</span>',
                            unsafe_allow_html=True)
                for it in card:
                    mins = f'<span class="cite"> · {it.minutes}</span>' if it.minutes else ""
                    ask = ""
                    if it.ask_verbatim:
                        ask = (f'<div style="margin-top:6px;padding:8px 12px;background:#f2f0ea;'
                               f'border-left:2px solid var(--ink);"><span class="cite">'
                               f'<b>Say this:</b> {it.ask_verbatim}</span></div>')
                    st.markdown(
                        f'<div class="card">'
                        f'<b>Step {it.rank}: {it.question}</b>{mins}<br><br>'
                        f'<b>→ Do this now:</b> {it.do_now or it.where}<br>'
                        f'{ask}'
                        f'<span class="cite" style="display:block;margin-top:8px;">'
                        f'<b>What we already know:</b> {it.have}<br>'
                        f'{"<b>Where:</b> " + it.where + "<br>" if it.do_now and it.where else ""}'
                        f'<b style="color:#7a2518;">✕ Drop the lot if:</b> {it.kills_if}'
                        f'</span></div>',
                        unsafe_allow_html=True)

st.markdown("---")

# ---- the short list Tal builds by starring lots as he goes ----
_internal = [c for c in ["_card", "_f", "_override", "_breakeven", "_pf"] if c in df.columns]
if shortlist:
    sl = df[df.Address.isin(shortlist)]
    st.markdown(f"### ★ Your short list — {len(sl)} lot{'s' if len(sl) != 1 else ''}")
    st.markdown('<span class="cite">The lots you starred. Download it, or clear and '
                'start again.</span>', unsafe_allow_html=True)
    for _, s in sl.iterrows():
        mark = " ★your numbers" if s.get("_override") else ""
        roc = f"{s.ROC:.0%} ROC" if pd.notna(s.ROC) else s.Signal
        ask = f"${s.Price:,.0f}" if pd.notna(s.Price) else "—"
        st.markdown(f'<div class="card">{sig_stamp(s.Signal)} &nbsp; <b>{s.Address}</b>'
                    f'<br><span class="cite">{ask} ask · {roc}{mark}</span></div>',
                    unsafe_allow_html=True)
    sc1, sc2 = st.columns([1, 1])
    with sc1:
        # The short list is a handoff document, not a row dump. It has to carry the
        # numbers Tal was looking at when he starred the lot — including any scenario
        # he modelled — so it stands on its own in an email to Michael or the partners.
        out_rows = []
        for _, s in sl.iterrows():
            f = s.get("_f") or {}
            o = overrides.get(s.Address, {})
            pf_s = s.get("_pf")
            cost = profit = exit_used = None
            if pf_s is not None:
                bb = pf_s.run().get("base") or {}
                cost = bb.get("total_cost"); profit = bb.get("profit")
                exit_used = pf_s.exit_psf_basis
            nxt = ("Verify prior sqft, then call the agent"
                   if s.Signal in ("STRONG", "BUY")
                   else "Only if the price moves — see the walk-away number")
            out_rows.append({
                "Address": s.Address,
                "Signal": s.Signal,
                "Return on cost": f"{s.ROC:.0%}" if pd.notna(s.ROC) else "",
                "Asking price": f"${s.Price:,.0f}" if pd.notna(s.Price) else "",
                "Offer modelled": (f"${float(o['offer']):,.0f}" if o.get("offer")
                                   else "(at full asking)"),
                "Buildable sqft": f"{s.Buildable:,.0f}" if pd.notna(s.Buildable) else "",
                "Construction $/sf used": f"${float(o.get('constr') or a.construction_psf):,.0f}",
                "Exit $/sf used": f"${exit_used:,.0f}" if exit_used else "",
                "Total cost": f"${cost:,.0f}" if cost else "",
                "Profit": f"${profit:,.0f}" if profit else "",
                "Walk-away number": s.get("_breakeven") or "",
                "Running on my own numbers?": "YES" if o else "no",
                "Jurisdiction": s.Jurisdiction,
                "Next step": nxt,
            })
        sbuf = io.StringIO()
        pd.DataFrame(out_rows).to_csv(sbuf, index=False)
        st.download_button("Download my short list", sbuf.getvalue(),
                           "short_list.csv", "text/csv",
                           help="Address, signal, return, your modelled offer, the cost "
                                "stack, the walk-away number and the next step — one row "
                                "per lot, ready to send on.")
    with sc2:
        # the same starred lots, but as the diligence checklist to work through
        srows = []
        for _, s in sl.iterrows():
            card = s.get("_card")
            if isinstance(card, list) and card:
                srows.extend(card_to_rows(s.Address, card))
        if srows:
            swbuf = io.StringIO()
            pd.DataFrame(srows).to_csv(swbuf, index=False)
            st.download_button("Download the checklist for these lots", swbuf.getvalue(),
                               "short_list_diligence.csv", "text/csv",
                               help="Just the starred lots, as the step-by-step checklist "
                                    "with blank columns to fill in.")
    if st.button("Clear the short list"):
        st.session_state["_shortlist"] = set()
        st.rerun()
    st.markdown("---")
else:
    st.markdown('<span class="cite">★ Star any lot above to build a short list you can '
                'download.</span>', unsafe_allow_html=True)
    st.markdown("---")

c1, c2 = st.columns(2)
with c1:
    buf = io.StringIO()
    df.drop(columns=_internal).to_csv(buf, index=False)
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
