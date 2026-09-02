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
import guide
from engine import (BUILD, Assumptions, CompMarket, ProForma, sensitivity,
                    what_youd_have_to_believe, discount_to_breakeven, path_to_strong)
from diligence import build_card, card_to_rows
from coastal import coastal_flag
from verification import (Verified, margin_over_market, rank_score,
                          confidence_note, ladbs_links)
from cofo_parser import parse_cofo, parse_cofo_pdf, to_csv_row
from underwrite import (waterfall, compare_structures, what_breaks_it, offer_grid)
from construction import area_construction_cost
from engine import ula_tax, cliff_advice

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


# ---- sidebar ------------------------------------------------------------------
# Streamlit fills the sidebar in call order, and the short list is only known after
# the lot loop runs — which would put it below six sliders, off-screen. Reserve a
# container at the very top now and fill it later, so the basket is the first thing
# in the sidebar and visible without scrolling anything.
_sl_slot = st.sidebar.container()

st.sidebar.markdown("### The two that matter")
st.sidebar.caption("Construction cost and exit price move the answer roughly five "
                   "times more than anything else below. Everything is a slider, but "
                   "these are the ones to think about.")
# Build the yardstick. Guard against a stale engine.py: if only one of the two files
# has been updated, an unknown keyword would otherwise kill the whole app before it
# renders anything. Better to run with the feature disabled and say so.
_cap = st.sidebar.expander("Capital structure")
_adv = st.sidebar.expander("Other assumptions")

_assump_kwargs = dict(
    construction_psf=st.sidebar.number_input("Construction $/sqft — fallback only", 400, 2000, 1000, 50,
        help="Used only where the street is not recognised as Alphabet flats ($700) or hillside ($1,150). Most Palisades lots never touch this number; the per-lot figure is shown on each row."),
    contingency_pct=_adv.slider("Contingency", 0.0, 0.20, 0.08, 0.01),
    carrying_rate=_adv.slider("Carrying rate /yr", 0.0, 0.10, 0.03, 0.005),
    selling_cost_pct=_adv.slider("Selling cost", 0.0, 0.10, 0.05, 0.005),
    appreciation_pct=_adv.slider("Appreciation /yr", -0.05, 0.10, 0.03, 0.005,
        help="Observed Palisades drift is about 1.5%/yr. 3% is already optimistic."),
    new_build_premium=_adv.slider("New-build premium", 0.0, 0.30, 0.10, 0.01,
        help="Measured at 19-26% size-controlled from 1,036 Palisades sales."),
    land_ltv=_cap.slider("Lender advance on LAND", 0.0, 0.80, 0.50, 0.05,
        help="Tal's structure is 50% down on the land, i.e. a 50% advance."),
    construction_ltc=_cap.slider("Lender advance on BUILD costs", 0.0, 1.0, 1.00, 0.05,
        help="Construction fully financed in the default structure."),
    loan_rate=_cap.slider("Construction loan rate", 0.05, 0.15, 0.105, 0.005),
    build_months=st.sidebar.slider("Build months", 10, 42, 30, 1,
        help="Two Palisades builds pulled from LADBS ran 34 and 35 months. "
             "18 is the base case; slide it to see the cost of a longer schedule."),
    ae_pct=_adv.slider("Architecture & engineering", 0.0, 0.12, 0.05, 0.01),
    apply_ula=_adv.checkbox(
        "Apply Measure ULA (mansion tax)", value=True,
        help="4% and 5.5% on LA city sales above the tiers, on the WHOLE price, paid "
             "by the seller, plus 0.56% documentary transfer tax at any price. "
             "Thresholds index to Chained CPI each 1 July, so the tiers at a 2028-29 "
             "exit are materially higher than today's. NOTE: the repeal measure was "
             "withdrawn on 25 June 2026 before qualifying and was replaced by a "
             "measure that does not touch transfer taxes — so ULA should be "
             "underwritten as permanent."),
    exit_year=_adv.number_input("Exit year (sets the ULA tier)", 2026, 2035, 2028, 1,
        help="Thresholds index each 1 July. A 2029 exit faces roughly $5.82M and "
             "$11.74M rather than $5.4M and $10.9M."),
    scarcity_premium=_adv.slider(
        "SCARCITY BET — extra exit premium", 0.0, 0.40, 0.00, 0.05,
        help="The 2028-29 thesis: a rebuilt, supply-constrained Palisades sells above "
             "what today's comps imply. Zero by default because it is a forecast, not "
             "an observation — Palisades sales through mid-2026 are roughly flat "
             "(~+1.5%/yr size-controlled), below the 3% appreciation already assumed. "
             "Turn it on to see the upside case; it stays labelled as a bet."),
)
try:
    a = Assumptions(**_assump_kwargs)
except TypeError:
    _supported = set(getattr(Assumptions, "__dataclass_fields__", {}))
    _dropped = [k for k in _assump_kwargs if k not in _supported]
    a = Assumptions(**{k: v for k, v in _assump_kwargs.items() if k in _supported})
    st.sidebar.error(
        "**engine.py is out of date.** Ignoring: " + ", ".join(_dropped) +
        ". Update engine.py in the repo (and reboot the app from Manage app) to enable it.")
st.sidebar.markdown(f'<span class="cite">{a.stamp()}</span>', unsafe_allow_html=True)
if getattr(a, "scarcity_premium", 0):
    st.sidebar.warning(f"Scarcity bet ON (+{a.scarcity_premium:.0%}). Every number below "
                       f"includes a forecast the current data does not yet support. "
                       f"Base case is this slider at 0.")

st.sidebar.markdown("### Negotiation scenario")
guide.render_guide_drawer()
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


# Uploaded comps rarely arrive with our exact column names — a Redfin sold export uses
# ADDRESS / SOLD DATE / PRICE / SQUARE FEET / $/SQUARE FEET. Map whatever comes in onto
# the schema the matcher needs, or the rows land with every field blank and are silently
# useless. Worse, blank address+sold_date made pandas treat every uploaded row as a
# duplicate of every other, collapsing a whole file into a single comp.
_COMP_ALIASES = {
    "address": ["address", "addr", "street address", "full address", "property address"],
    "city": ["city", "town", "municipality"],
    "price": ["price", "sold price", "sale price", "last sold price", "close price",
              "sold_price", "sale_price"],
    "square_feet": ["square_feet", "square feet", "sq ft", "sqft", "sq.ft.", "living area",
                    "finished sqft", "total sqft", "building sqft"],
    "price_per_square_foot": ["price_per_square_foot", "$/square feet", "$/sq ft", "$/sqft",
                              "price per square foot", "price/sqft", "ppsf", "$ per sqft"],
    "sold_date": ["sold_date", "sold date", "sale date", "close date", "date sold",
                  "last sold date", "sold on"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon", "long"],
    "year_built": ["year_built", "year built", "yr built"],
    "neighborhood_or_location": ["neighborhood_or_location", "neighborhood", "location",
                                 "area", "subdivision"],
    "area_flag": ["area_flag", "area flag", "in palisades", "burn area"],
}


def palisades_only(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only Pacific Palisades sales.

    The fund's exit is a Palisades house, so the exit basis should be built from
    Palisades trades. Santa Monica and wider-LA sales are a different market and
    drag the basis in whichever direction that market happens to sit — the same
    never-blend rule already enforced between Malibu and Palisades.

    Prefers an explicit area flag when the source provides one (Tal's export marks
    each sale 'Pacific Palisades' or 'Outside Palisades'); otherwise falls back to
    the city field.
    """
    if "area_flag" in df.columns and df["area_flag"].notna().any():
        flag = df["area_flag"].astype(str).str.strip().str.lower()
        keep = flag.eq("pacific palisades")
        # rows with no flag fall through to the city test
        unflagged = ~flag.isin(["pacific palisades", "outside palisades"])
        if "city" in df.columns:
            city_ok = df["city"].astype(str).str.strip().str.lower().str.startswith(
                ("pacific palisades", "pacific plsds"))
            keep = keep | (unflagged & city_ok)
        return df[keep]
    if "city" in df.columns:
        city = df["city"].astype(str).str.strip().str.lower()
        return df[city.str.startswith(("pacific palisades", "pacific plsds"))]
    return df


def normalize_comps(df: pd.DataFrame):
    """Map an arbitrary comps CSV onto our schema. Returns (df, notes)."""
    notes = []
    lookup = {str(c).strip().lower(): c for c in df.columns}
    out = pd.DataFrame(index=df.index)
    for canon, aliases in _COMP_ALIASES.items():
        src = next((lookup[al] for al in aliases if al in lookup), None)
        if src is not None:
            out[canon] = df[src]
    # strip currency/commas so "$3,750,000" and "1,234" parse as numbers
    for col in ("price", "square_feet", "price_per_square_foot", "latitude",
                "longitude", "year_built"):
        if col in out.columns:
            out[col] = pd.to_numeric(
                out[col].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                errors="coerce")
    # derive $/sqft per row wherever it's missing but price and size are present —
    # a blank cell shouldn't cost us an otherwise good comp
    if "price" in out.columns and "square_feet" in out.columns:
        if "price_per_square_foot" not in out.columns:
            out["price_per_square_foot"] = pd.NA
        derivable = (out["price_per_square_foot"].isna() & out["price"].notna()
                     & out["square_feet"].notna() & (out["square_feet"] > 0))
        n_derived = int(derivable.sum())
        if n_derived:
            out.loc[derivable, "price_per_square_foot"] = (
                out.loc[derivable, "price"] / out.loc[derivable, "square_feet"]).round(0)
            notes.append(f"derived $/sqft for {n_derived} row(s) from price ÷ size")
    if "sold_date" in out.columns:
        out["sold_date"] = pd.to_datetime(out["sold_date"], errors="coerce")
    # the matcher needs size and $/sqft; anything without both can't be scored
    before = len(out)
    need = [c for c in ("square_feet", "price_per_square_foot") if c in out.columns]
    if len(need) == 2:
        out = out[out.square_feet.notna() & (out.square_feet > 0) &
                  out.price_per_square_foot.notna() & (out.price_per_square_foot > 0)]
    dropped = before - len(out)
    if dropped:
        notes.append(f"{dropped} row(s) skipped — missing size or $/sqft")
    missing = [c for c in ("address", "city", "square_feet", "price_per_square_foot")
               if c not in out.columns]
    if missing:
        notes.append("columns not found: " + ", ".join(missing))
    if "latitude" not in out.columns or "longitude" not in out.columns:
        notes.append("no coordinates — these comps won't be distance-weighted")
    return out.reset_index(drop=True), notes


with st.sidebar:
    st.markdown("### Comps")
    comps_up = st.file_uploader("Add more comps (CSV)", type=["csv"],
                                key="comps_upload",
                                help="Any column names work — Redfin's sold export is "
                                     "fine. Needs at least an address, the size, and "
                                     "either $/sqft or the price.")
    comps_mode = st.radio("How to use them", ["Add to the existing comps", "Replace them"],
                          index=0, key="comps_mode",
                          help="Add is almost always right — more recent sales make the "
                               "exit estimate better.")
    pal_only = st.checkbox("Pacific Palisades sales only", value=True, key="pal_only",
                           help="The exit is a Palisades house, so price it off Palisades "
                                "trades. Unticking pulls in Santa Monica and wider-LA "
                                "sales, which are a different market.")

base_comps = load_comps()
if comps_up is not None:
    raw_new = pd.read_csv(comps_up)
    new_comps, notes = normalize_comps(raw_new)
    if comps_mode.startswith("Add"):
        before = len(base_comps)
        comps_df = pd.concat([base_comps, new_comps], ignore_index=True)
        # Dedupe ONLY where both keys are present. Rows with a blank address or date
        # are not duplicates of each other — that assumption is what collapsed an
        # entire uploaded file down to one comp.
        if {"address", "sold_date"}.issubset(comps_df.columns):
            keyed = comps_df.dropna(subset=["address", "sold_date"])
            unkeyed = comps_df[~comps_df.index.isin(keyed.index)]
            keyed = keyed.drop_duplicates(subset=["address", "sold_date"], keep="last")
            comps_df = pd.concat([keyed, unkeyed], ignore_index=True)
        added = len(comps_df) - before
        comps_sig = f"merge-{len(comps_df)}-{comps_up.name}"
        st.sidebar.success(f"{len(comps_df):,} comps in play — {added:,} added to the "
                           f"original {before:,}")
        st.sidebar.caption(f"Read {len(raw_new):,} row(s) from your file.")
    else:
        comps_df = new_comps
        comps_sig = f"replace-{len(comps_df)}-{comps_up.name}"
        st.sidebar.warning(f"Using only your {len(comps_df):,} comps")
    for n in notes:
        st.sidebar.caption(f"· {n}")
else:
    comps_df = base_comps
    comps_sig = "bundled"
    st.sidebar.caption(f"Using the bundled {len(base_comps):,} sold sales")

if pal_only:
    _before_f = len(comps_df)
    comps_df = palisades_only(comps_df)
    st.sidebar.caption(f"Palisades only: {len(comps_df):,} of {_before_f:,} sales in play")

mkt = CompMarket(comps_df)

# ---- verified records: paste a Certificate of Occupancy ----
# The LADBS pull is the only trustworthy source for prior area, and it can't be
# automated. What CAN be removed is the transcription: paste the certificate text
# and every field the model needs is extracted and tagged CERTIFIED. Entries
# accumulate across the session and export as a CSV that feeds straight back in.
_vault = st.session_state.setdefault("_verified_records", {})

with st.expander(f"Verified records — upload or paste a Certificate of Occupancy  "
                 f"({len(_vault)} on file)"):
    st.markdown(
        '<span class="cite">Open the property on LADBS, click <b>Certificate of '
        'Occupancy</b>, open the PDF, select all the text and copy it. Paste below. '
        'This pulls floor area, height, stories, basement levels, lot size, zone, '
        'Coastal Zone, Hillside Ordinance, ESA and fire district in one go.<br><br>'
        '<b>Why it matters:</b> every prior-square-footage figure we have checked '
        'against a working sheet was wrong, and always overstated. A certified '
        'figure outranks everything else in the model.</span>',
        unsafe_allow_html=True)
    _pdfs = st.file_uploader(
        "Certificate of Occupancy PDF — upload one or several",
        type=["pdf"], accept_multiple_files=True, key="cofo_pdfs",
        help="On LADBS, open Certificate of Occupancy and use Print as PDF, or open "
             "the PDF icon and save it. Drop the file here — no typing.")
    if _pdfs:
        for _pf in _pdfs:
            _p = parse_cofo_pdf(_pf)
            if _p.get("ok"):
                _row = to_csv_row(_p, "")
                _key = (_row["ADDRESS"] or _pf.name).strip()
                _vault[_key] = _row
                st.success(f"{_pf.name} → {_key}  ·  "
                           f"{_p.get('prior_sqft'):,.0f} sf, "
                           f"{_p.get('prior_height_ft', 0):.1f} ft, "
                           f"{_p.get('stories', '?')} storeys")
            elif _p.get("scanned"):
                st.warning(f"{_pf.name}: scanned image, no text layer. Older "
                           f"certificates are photographs of paper. Read the figures "
                           f"off it and use the manual entry below.")
            else:
                for _n in _p.get("notes", []):
                    st.error(f"{_pf.name}: {_n}")
            for _n in _p.get("notes", [])[1:]:
                st.info(_n)

    st.markdown('<span class="cite">If the PDF is a scan, or you only have the page on '
                'screen, paste the text instead:</span>', unsafe_allow_html=True)
    _cv1, _cv2 = st.columns([2, 1])
    with _cv1:
        _paste = st.text_area("Certificate text (fallback)", height=120,
                              key="cofo_paste",
                              placeholder="Paste the STRUCTURAL INVENTORY and PARCEL "
                                          "INFORMATION blocks.")
    with _cv2:
        _addr_for = st.text_input("Address (if not in the text)", key="cofo_addr")
        if st.button("Read pasted text", key="cofo_go") and _paste:
            _p = parse_cofo(_paste)
            if _p.get("ok"):
                _row = to_csv_row(_p, _addr_for)
                _key = (_row["ADDRESS"] or _addr_for or f"record {len(_vault)+1}").strip()
                _vault[_key] = _row
                st.success(f"Read: {_key}")
            else:
                st.error("Couldn't find a floor area or lot size in that text.")
            for _n in _p.get("notes", []):
                st.warning(_n)

    if _vault:
        _vdf = pd.DataFrame(list(_vault.values()))
        st.dataframe(_vdf, use_container_width=True, hide_index=True)
        _vb = io.StringIO(); _vdf.to_csv(_vb, index=False)
        _d1, _d2 = st.columns(2)
        with _d1:
            st.download_button("Download verified records", _vb.getvalue(),
                               "verified_records.csv", "text/csv", key="dl_vault")
        with _d2:
            if st.button("Clear", key="clr_vault"):
                st.session_state["_verified_records"] = {}
                st.rerun()
        st.markdown('<span class="cite">Add these columns to your Redfin CSV — or '
                    'merge this file into it — and the analyzer will use the certified '
                    'figures and rank them above unverified lots.</span>',
                    unsafe_allow_html=True)

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
        one_prior = st.number_input("Prior sqft (optional)", 0, 200_000, 0, 100,
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
# bump the version segment whenever the fact-gathering logic changes, or lots
# cached by an older build linger with fields the display now expects.
_sig = f"v3-{len(raw)}-{hash(tuple(raw[addr_col].astype(str)))}-{comps_sig}"
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

        # Verified fields, when the CSV carries them (from the C of O parser or
        # entered by hand). These outrank the county record and the working sheet.
        def _col(*names):
            for nm in names:
                for c in raw.columns:
                    if str(c).upper().replace(" ", "_") == nm:
                        v = r.get(c)
                        if v is not None and not pd.isna(v):
                            return v
            return None
        _v_height  = _col("PRIOR_HEIGHT_FT", "PRIOR_HEIGHT")
        _v_lot     = _col("LOT_SQFT")
        _v_src     = _col("SOURCE", "PRIOR_SQFT_SOURCE")
        _v_coastal = _col("COASTAL_ZONE")
        _v_hill    = _col("HILLSIDE")

        # Lot size drives the EO8 zoning envelope, and Redfin exports carry it.
        # Previously we only used the county's figure, so any lot the county lookup
        # missed had no zoning path at all — which silently suppressed the larger of
        # the two envelopes on exactly the cheap lots we care about.
        csv_lot = None
        _lot_raw = None
        for _c in raw.columns:
            if "LOT SIZE" in str(_c).upper() or str(_c).upper() == "LOT_SQFT":
                _lot_raw = r.get(_c); break
        if _lot_raw is not None and not pd.isna(_lot_raw):
            try:
                _v = float(str(_lot_raw).replace(",", "").replace("$", "").strip())
                # Redfin gives acres on large parcels; convert anything implausibly small
                csv_lot = round(_v * 43_560) if 0 < _v < 100 else round(_v)
            except (TypeError, ValueError):
                csv_lot = None

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

        # county lot size wins; CSV fills the gap
        if _v_lot is not None:
            try: p.lot_sqft = float(_v_lot)
            except Exception: pass
        if csv_lot and not getattr(p, "lot_sqft", None):
            try: p.lot_sqft = csv_lot
            except Exception: pass

        j = jur.route(p.situs_city if p.found else (None if pd.isna(city) else str(city)))
        # RTI / plans-in-hand: Redfin remarks often say so outright. A lot that is
        # already permitted has cleared review — real soft-cost and schedule savings.
        _blob = " ".join(str(r.get(c, "")) for c in raw.columns
                         if any(k in str(c).upper() for k in
                                ("REMARK", "DESCRIPTION", "NOTE", "URL"))).upper()
        _rti = any(k in _blob for k in
                   ("RTI", "READY TO ISSUE", "READY-TO-ISSUE", "SHOVEL READY",
                    "SHOVEL-READY", "PERMITS IN HAND", "PERMITTED", "APPROVED PLANS",
                    "PLANS APPROVED", "FULLY ENTITLED", "ENTITLED"))
        _cost = area_construction_cost(addr, default=a.construction_psf)
        f = dict(Address=addr, Jurisdiction=j.name, jcode=j.code,
                 lat=(None if pd.isna(lat) else float(lat)),
                 lon=(None if pd.isna(lon) else float(lon)),
                 rti=_rti, area_psf=_cost["psf"], area_band=_cost["band"],
                 area_why=_cost["why"],
                 prior_height_ft=(float(_v_height) if _v_height is not None else None),
                 area_source=(str(_v_src).upper() if _v_src else None),
                 verified_coastal=_v_coastal, verified_hillside=_v_hill,
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

        build = None; build_basis = ""; upside = None; envelope = None
        if j.code == "MALIBU" and p.prior_sqft:
            ph, _ = ceiling_from_year(p.year_built)
            if ph:
                build = envelope_both_cases(p.prior_sqft, ph, 10.0)["as_of_right"]["habitable"]
                build_basis = "as-of-right rebuild"
        elif j.code == "CITY_OF_LA" and (p.prior_sqft or p.lot_sqft):
            # Take the GREATER of the EO1 rebuild envelope and the EO8 zoning
            # envelope. Computing EO1 alone systematically understates lots where a
            # small or single-storey house burned — which are the cheapest to buy.
            be = jur.best_envelope(
                p.prior_sqft, lot_sqft=p.lot_sqft,
                prior_height_ft=(float(_v_height) if _v_height is not None else None),
                coastal=bool(_v_coastal) if _v_coastal is not None else False,
                hillside=bool(_v_hill) if _v_hill is not None else False)
            build = be.get("best_sqft")
            upside = be.get("eo1_upside") or be.get("eo8_bonus")
            build_basis = ("EO8 zoning (R1 0.45 FAR)" if be.get("best_path") == "EO8 zoning"
                           else "EO1 base (rebuild same massing)")
            envelope = be
        f.update(Buildable=build, build_basis=build_basis, upside=upside,
                 envelope=envelope)

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
    # cost priority: explicit per-lot override > area-derived default > sidebar
    _psf = o.get("constr") or f.get("area_psf") or a_.construction_psf
    a_lot = a_
    if float(_psf) != float(a_.construction_psf):
        a_lot = Assumptions(**{**a_.__dict__, "construction_psf": float(_psf)})
    # RTI: plans already approved means lower soft cost and a shorter carry. Model it
    # as a shorter hold rather than inventing a soft-cost line the model doesn't have.
    if f.get("rti") and not o.get("hold_override"):
        a_lot = Assumptions(**{**a_lot.__dict__,
                               "hold_years_express": max(1.0, a_lot.hold_years_express - 0.5),
                               "hold_years_standard": max(1.5, a_lot.hold_years_standard - 0.75)})

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
            matched_comps=f["comps"], lot_flags=f["flags"] or None, breakeven=None,
            coastal_tier=(coastal_flag(f.get("jcode"), f.get("lat"), f.get("lon"),
                                       f["Address"]) or {}).get("tier"))

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
    tags = []
    if f.get("rti"): tags.append("RTI/permitted")
    if f.get("area_band") == "alphabet-flats": tags.append("flats — build ~$700/sf")
    elif f.get("area_band") == "hillside": tags.append("hillside — build ~$1,150/sf")
    if rr["base"].get("ula_tax"): tags.append(f"ULA ${rr['base']['ula_tax']:,.0f}")
    tagstr = (" · " + " · ".join(tags)) if tags else ""
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
                  f"(range {rr['low']['roc']:.0%}–{rr['high']['roc']:.0%}){scen}{tagstr}. "
                  f"{row['_breakeven']}")
    row["_cliff"] = cliff_advice(rr["base"]["gross_sale"],
                                 exit_year=getattr(a_, "exit_year", 2026),
                                 index_rate=getattr(a_, "ula_index_rate", 0.025))

    # ---- margin over market: the metric that actually separates lots ----
    # Solve the exit price at which this lot returns exactly zero, then compare it
    # to the matched comparable median. Everything on the cost side collapses into
    # the breakeven; everything on the revenue side into the median.
    # the engine now solves this directly, against TODAY's market rather than an
    # escalated one — the conservative framing
    row["_breakeven_psf"] = pf.breakeven_sale_psf()

    # provenance of the prior-area figure this lot's economics rest on
    _src = ("CERTIFIED" if f.get("area_source") == "CERTIFIED"
            else "PERMIT" if f.get("area_source") == "PERMIT"
            else "ASSESSOR" if f.get("prior_from_county")
            else "SHEET" if f.get("prior_sqft") else "NONE")
    _v = Verified(f.get("prior_sqft"), _src, height_ft=f.get("prior_height_ft"))
    row["_verified"] = _v
    _mm = margin_over_market(row["_breakeven_psf"], basis)
    row["_margin"] = _mm
    row["_rank_score"] = rank_score(_mm["margin"] if _mm else None,
                                    _v.weight, bool(_v.height_ft))
    row["_rti"] = bool(f.get("rti"))
    # rebuild the card now that we know the walk-away number, so step 4 carries it
    row["_card"] = build_card(
        address=f["Address"], jurisdiction=f["jcode"], prior_sqft=f["prior_sqft"],
        imp_value=f["imp_value"], is_beachfront=None, units=f["units"],
        matched_comps=f["comps"], lot_flags=f["flags"] or None,
        breakeven=row.get("_breakeven"),
        coastal_tier=(coastal_flag(f.get("jcode"), f.get("lat"), f.get("lon"),
                                   f["Address"]) or {}).get("tier"))
    return row


df = pd.DataFrame([_score(f, a, discount) for f in facts])
tier = {"STRONG":0,"BUY":1,"MAYBE":2,"PASS":3,"NO COMPS":4,"NEED PRICE":5,
        "NEED PRIOR SF":6,"—":7,"NO DATA":8}
df["_t"] = df.Signal.map(lambda s: tier.get(s, 7))
# Primary sort is margin over market with a provenance penalty — a lot you can act
# on outranks one that merely looks good. ROC only breaks ties.
if "_rank_score" in df.columns and df["_rank_score"].notna().any():
    df = df.sort_values(["_t", "_rank_score", "ROC"],
                        ascending=[True, True, False], na_position="last").drop(columns="_t")
else:
    df = df.sort_values(["_t","ROC"], ascending=[True, False],
                        na_position="last").drop(columns="_t")

n_scored = df.ROC.notna().sum()
st.markdown("---")
st.markdown(f"### Results — {len(df)} lots, best to worst")
st.markdown(f'<span class="cite">{n_scored} priceable · {len(df)-n_scored} eligible but '
            f'not yet priceable (a data gap, not a rejection).</span>',
            unsafe_allow_html=True)
st.caption(f"Priced at full asking · yardstick: {a.stamp()}")
if getattr(a, "scarcity_premium", 0):
    st.error(f"**Upside case, not the base case.** Every return below includes a "
             f"+{a.scarcity_premium:.0%} scarcity premium on the exit price — the "
             f"2028-29 supply-constraint thesis. Palisades sales through mid-2026 are "
             f"roughly flat, so this is an argument to be made, not a measurement. "
             f"Set the slider to 0 for the defensible base case.")

with st.expander("How to use this list", expanded=False):
    st.markdown("""
**The table is the screen. The panel below it is the decision.**

**1 · Read the table.** One row per lot, sorted by *margin over market* — how far
above the comparable median a lot has to sell just to break even. Negative is margin
in your favour before the market has to move at all. Click any header to re-sort.

**2 · Check the Verified column.** "no" means the prior square footage came from a
sheet or a listing rather than a Certificate of Occupancy. Every unverified figure
we have checked was wrong, and always overstated — so an unverified lot near the top
is a lot to verify, not a lot to buy.

**3 · Tick ★** on anything worth keeping. The short list collects in the sidebar and
downloads with the numbers attached.

**4 · Pick one property below** for the full underwriting: the waterfall and what the
investor actually receives, whether leverage helps this specific deal, and which
assumption ends it if it's wrong.

**5 · Upload Certificates of Occupancy** as you pull them (the panel at the top).
Each one you add makes the ranking more honest and moves that lot to "verified".
    """)

shortlist = st.session_state.setdefault("_shortlist", set())


def render_detail(x, f, a, discount, overrides):
    """
    Everything about ONE lot, full width.

    Previously each of these blocks rendered as a collapsed expander beneath every
    row. Six panels across 130 lots is nearly 800 collapsed elements on a single
    page: slow to render, and impossible to navigate because the thing you need
    looks identical to five things you don't.

    Screening and underwriting are different jobs and now have different views. The
    table answers "which lots"; this answers "is this the one".
    """

    # The header card is rendered by the caller immediately above this call, with the
    # margin tier line the version here lacked. This block was a leftover duplicate
    # from that refactor and referenced `css` and `bits`, which are local to the
    # scoring loop and undefined here — a NameError on every property opened.

    # the per-lot facts live on the row. `f` from the scoring loop is NOT in scope
    # here — reading it directly crashed on the first row that had none (the blank
    # "nan" row from a trailing line in the CSV).
    f = x.get("_f") or {}

    # ---- ULA threshold cliff: selling for less can net more ----
    if x.get("_cliff"):
        st.markdown(f'<div class="card card-warn">{x["_cliff"]}</div>',
                    unsafe_allow_html=True)
    # ---- SECOND STAGE: the full underwriting on one chosen deal ----
    # The ranking above is a sorting job. This is the step after: what the
    # investor actually receives, what leverage does in both directions, and
    # which assumption ends the deal if it is wrong.
    if x.get("_pf") is not None and pd.notna(x.Buildable) and pd.notna(x.Price):
        with st.expander("Underwrite this deal — waterfall, structures, what breaks it"):
            _sq, _ld = float(x.Buildable), float(x.Price)
            _basis = (f.get("comp_basis") or 0)
            _mm2 = (x.get("_margin") if isinstance(x.get("_margin"), dict) else {})
            _median = _mm2.get("median") or _basis
            _exit = st.number_input(
                "Exit price to underwrite ($/sf)", 500, 6000,
                int(round(_basis or 1700)), 50, key=f"uw_exit_{x.Address}",
                help="Defaults to the matched comp basis. The market median for "
                     "this street and size band is shown below for reference.")
            st.markdown(f'<span class="cite">Comparable median '
                        f'<b>${_median:,.0f}/sf</b> · this lot breaks even at '
                        f'<b>${x.get("_breakeven_psf", 0):,.0f}/sf</b></span>',
                        unsafe_allow_html=True)

            _base_a = Assumptions(**{**a.__dict__,
                                     "construction_psf": float(
                                         f.get("area_psf") or a.construction_psf)})
            _pf2 = ProForma(_sq, _ld, _exit, f["jcode"], _base_a, express=False)
            _r2 = _pf2._run_one(_exit)
            _w = waterfall(_r2["profit"], _r2["equity"],
                           months=_base_a.total_months)

            st.markdown("**What the investor receives**")
            st.markdown(
                f'<div class="card"><span class="cite">'
                f'Total project cost <b>${_r2["total_cost"]:,.0f}</b> · '
                f'equity <b>${_r2["equity"]:,.0f}</b> · '
                f'profit <b>${_r2["profit"]:,.0f}</b><br><br>'
                f'<b>LP</b> — puts in ${_w["lp_capital"]:,.0f}, receives '
                f'${_w["lp_total"]:,.0f}. <b>{_w["lp_multiple"]:.2f}x</b> over '
                f'{_base_a.total_months:.0f} months, roughly '
                f'<b>{_w["lp_irr"]:.0%} IRR</b>.<br>'
                f'<b>GP</b> — puts in ${_w["gp_capital"]:,.0f}, receives '
                f'${_w["gp_total"]:,.0f} (<b>{_w["gp_multiple"]:.1f}x</b>).<br><br>'
                f'<b>Effective promote {_w["effective_promote"]:.0%}.</b> A 50% '
                f'profit share on 10% of the capital. Normal for a friends-and-'
                f'family single asset; institutions expect roughly 20% over a '
                f'preferred return at fund stage. And note losses follow capital, '
                f'not the split — on a loss the LP wears 90%, because the GP\'s '
                f'50% is upside only.</span></div>', unsafe_allow_html=True)

            st.markdown("**Does leverage help this deal?**")
            _rows = compare_structures(_sq, _ld, _exit, f["jcode"], _base_a,
                                       downside_psf=_median)
            st.dataframe(pd.DataFrame([{
                "Structure": s["name"],
                "Equity in": f"${s['equity']:,.0f}",
                "Breakeven $/sf": f"${s['breakeven']:,.0f}",
                f"CoC @ ${_exit:,}": f"{s['coc']:.0%}",
                f"CoC @ ${_median:,.0f}": f"{s.get('down_coc', 0):.0%}",
            } for s in _rows]), use_container_width=True, hide_index=True)
            st.markdown('<span class="cite">The breakeven barely moves across '
                        'structures — it is the same project cost either way. '
                        'Leverage changes who earns the profit and how hard a miss '
                        'lands, not whether the deal works.</span>',
                        unsafe_allow_html=True)

            st.markdown("**What breaks it** — ranked by damage")
            for _t in what_breaks_it(_sq, _ld, _exit, f["jcode"], _base_a):
                st.markdown(
                    f'<div class="card"><span class="cite">'
                    f'<b>{_t["factor"]}</b> → return on cost {_t["roc"]:.0%} '
                    f'(<b>{_t["delta"]*100:+.0f} points</b>)<br>{_t["note"]}'
                    f'</span></div>', unsafe_allow_html=True)

            st.markdown("**What to offer**")
            _g = offer_grid(_sq, _ld, f["jcode"], _base_a, comp_median=_median)
            _cols = {"Offer": []}
            for _e in _g["exits"]:
                _cols[f"${_e:,.0f}/sf"] = []
            for _r in _g["rows"]:
                _cols["Offer"].append(
                    f"${_r['offer']:,.0f}" + (f"  -{_r['discount']:.0%}"
                                              if _r["discount"] else "  (ask)"))
                for _e, _c in zip(_g["exits"], _r["cells"]):
                    _cols[f"${_e:,.0f}/sf"].append(f"{_c['roc']:.0%}")
            st.dataframe(pd.DataFrame(_cols), use_container_width=True, hide_index=True)
            _md_col = f"${_g['exits'][1]:,.0f}/sf"
            st.markdown(
                f'<span class="cite">Rows are what you offer, the one variable you '
                f'control. Columns are what the market does, the one you control least. '
                f'<b>{_md_col} is the comparable median</b> - where the market is now, '
                f'not where the deal needs it to be. Pick the column you actually '
                f'believe and read down to the first offer that clears.<br><br>'
                + (f'At the asking price this clears 20% once the market reaches '
                   f'<b>${_g["needed_exit"]:,.0f}/sf</b>. '
                   if _g["needed_exit"] else "")
                + (f'If the market only delivers its median, the offer has to come down '
                   f'<b>{_g["needed_discount"]:.0%}</b>.'
                   if _g["needed_discount"] is not None else
                   '<b>At the median exit no realistic discount on the land clears the '
                   'target</b> - the return is driven by build cost against exit price, '
                   'not by what you pay for the dirt.')
                + '</span>', unsafe_allow_html=True)

    # ---- what the economics actually rest on ----
    _v = x.get("_verified")
    if _v is not None:
        _css = "card" if _v.is_verified else "card card-warn"
        st.markdown(f'<div class="{_css}"><span class="cite">'
                    f'{confidence_note(_v, f.get("jcode","CITY_OF_LA"))}'
                    f'</span></div>', unsafe_allow_html=True)
        if not _v.is_verified:
            with st.expander("How to verify this in ten minutes (free)"):
                for step, detail in ladbs_links(x.Address).items():
                    st.markdown(f'<span class="cite"><b>{step}</b> — {detail}</span>',
                                unsafe_allow_html=True)

    # ---- which legal path gives the bigger house ----
    _env = f.get("envelope")
    if _env and _env.get("eo1_base") and _env.get("eo8_base"):
        _e1, _e8 = _env["eo1_base"], _env["eo8_base"]
        _win = "EO8 zoning" if _e8 > _e1 else "EO1 rebuild"
        with st.expander(f"Which path gives the bigger house? → {_win}"):
            st.markdown(
                f'<div class="card"><span class="cite">'
                f'<b>EO1 like-for-like:</b> {_e1:,} sf — rebuild what burned, '
                f'footprint and height both capped at 110%.<br>'
                f'<b>EO8 zoning-compliant:</b> {_e8:,} sf base, '
                f'{_env.get("eo8_bonus", 0):,} sf with the 20% design bonus — the '
                f'prior structure is not the ceiling, LAMC zoning is. Bypasses local '
                f'Coastal Act and CEQA review.<br><br>'
                f'<b>Underwritten on the larger: {max(_e1,_e8):,} sf via {_win}.</b>'
                f'{"<br><br>" + _env["note"] if _env.get("note") else ""}'
                f'</span></div>', unsafe_allow_html=True)

    if f.get("area_band") in ("alphabet-flats", "hillside"):
        st.markdown(f'<div class="card"><span class="cite"><b>Construction cost '
                    f'${f["area_psf"]:,.0f}/sf</b> — {f["area_why"]}</span></div>',
                    unsafe_allow_html=True)
    if f.get("rti"):
        st.markdown('<div class="card"><span class="cite"><b>Listing mentions RTI / '
                    'approved plans.</b> Shovel-ready means review is already cleared — '
                    'lower soft cost and a shorter carry, both modelled here as a '
                    'shorter hold. <b>Verify the permits are current and transfer</b>: '
                    'RTI status can lapse and permits have their own clocks. Get the '
                    'stamped set as a condition of purchase.</span></div>',
                    unsafe_allow_html=True)

    # ---- Coastal Commission exposure (Palisades) ----
    _cf = coastal_flag(f.get("jcode"), f.get("lat"), f.get("lon"), x.Address,
                       over_envelope=bool(f.get("upside")))
    if _cf and _cf["tier"] in ("HIGH", "LIKELY", "UNKNOWN"):
        _lbl = {"HIGH": "Coastal Commission — HIGH exposure, check before offering",
                "LIKELY": "Coastal Zone likely — worth a 2-minute check",
                "UNKNOWN": "Coastal Zone status unknown"}[_cf["tier"]]
        with st.expander(_lbl):
            st.markdown(f'<div class="card card-warn">{_cf["note"]}</div>',
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
            # Caps must never sit below the value we're seeding the box with, or
            # Streamlit raises StreamlitValueAboveMaxError and the page dies. Lots
            # like 860 Via De La Paz carry ~38,000 sf, well past any fixed ceiling,
            # so derive each max from the lot's own numbers.
            _v_off = int(o.get("offer") or (f.get("Price") or 0))
            _v_con = int(o.get("constr") or a.construction_psf)
            _v_bld = int(o.get("build") or f.get("Buildable") or 0)
            _v_xps = int(o.get("exit_psf") or f.get("comp_basis") or 0)
            w1, w2 = st.columns(2)
            with w1:
                offer = st.number_input(
                    "Your offer price ($)", 0, max(100_000_000, _v_off * 2),
                    _v_off, 25_000,
                    key=f"off_{x.Address}",
                    help="What you'd actually pay. The list prices at full asking; "
                         "drop this to see what a negotiated price does.")
                constr = st.number_input(
                    "Construction $/sqft", 0, max(3_000, _v_con * 2),
                    _v_con, 25,
                    key=f"con_{x.Address}",
                    help="A simple flat lot with good access builds cheaper than a "
                         "hillside. Default is the sidebar number.")
            with w2:
                bld = st.number_input(
                    "Buildable sqft", 0, max(60_000, _v_bld * 3),
                    _v_bld, 100,
                    key=f"bld_{x.Address}",
                    help="Override if you know the real prior house was bigger — "
                         "e.g. a multi-storey home with a basement the county "
                         "under-recorded.")
                xpsf = st.number_input(
                    "Exit $/sqft", 0, max(15_000, _v_xps * 3),
                    _v_xps, 50,
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

# ---------------------------------------------------------------- the table
# Screening view: every lot on one screen, sortable, scannable.
_view = df[~df.Address.astype(str).str.strip().str.lower().isin(["nan", "none", ""])].copy()


def _table_row(x):
    mm = (x.get("_margin") if isinstance(x.get("_margin"), dict) else {})
    v = x.get("_verified")
    return {
        "★": x.Address in shortlist,
        "Address": x.Address,
        "Signal": x.Signal,
        "Margin over market": (f"{mm['margin']:+.0%}" if mm else "—"),
        "Verified": ("yes" if (v is not None and getattr(v, "is_verified", False)) else "no"),
        "Breakeven $/sf": (f"${mm['breakeven']:,.0f}" if mm else "—"),
        "Buildable sf": (f"{x.Buildable:,.0f}" if pd.notna(x.Buildable) else "—"),
        "Ask": (f"${x.Price:,.0f}" if pd.notna(x.Price) else "—"),
        "$/buildable ft": (f"${x.Price / x.Buildable:,.0f}"
                           if pd.notna(x.Price) and pd.notna(x.Buildable) and x.Buildable
                           else "—"),
        "ROC": (f"{x.ROC:.0%}" if pd.notna(x.ROC) else "—"),
    }


_table = pd.DataFrame([_table_row(x) for _, x in _view.iterrows()])

st.markdown("#### The list")
st.markdown('<span class="cite">Sorted by margin over market — how far above the '
            'comparable median each lot has to sell just to break even, with unverified '
            'figures penalised. Click any column header to re-sort. Tick ★ to shortlist. '
            'Pick one below for the full underwriting.</span>', unsafe_allow_html=True)

if len(_table):
    guide.render_margin_legend()
    _edited = st.data_editor(
        _table, use_container_width=True, hide_index=True, key="results_table",
        disabled=[c for c in _table.columns if c != "★"],
        column_config=guide.apply_column_help({
            "★": st.column_config.CheckboxColumn("★", width="small",
                                                 help="Add to the short list"),
            "Margin over market": st.column_config.TextColumn(
                help="Breakeven sale price against the comparable median. Negative means "
                     "margin in your favour before the market has to move at all."),
            "Verified": st.column_config.TextColumn(
                help="Whether the prior square footage comes from a Certificate of "
                     "Occupancy or original permit rather than a sheet or listing."),
        }))
    if _edited is not None and "★" in _edited.columns:
        for _i, _r in _edited.iterrows():
            if _r["★"]:
                shortlist.add(_r["Address"])
            else:
                shortlist.discard(_r["Address"])

# ------------------------------------------------------------- one property
st.markdown("---")
st.markdown("#### Underwrite one property")
_choices = list(_view.Address)
if _choices:
    _pick = st.selectbox("Property", _choices, key="detail_pick",
                         label_visibility="collapsed")
    _sel = _view[_view.Address == _pick]
    if len(_sel):
        x = _sel.iloc[0]
        f = x.get("_f") or {}
        mm = (x.get("_margin") if isinstance(x.get("_margin"), dict) else {})
        _css = ("card card-strong" if x.Signal == "STRONG"
                else "card card-pass" if x.Signal == "PASS" else "card")
        _bits = [f"{x.Jurisdiction}"]
        if pd.notna(x.Price):
            _bits.append(f"${x.Price:,.0f} ask")
        if pd.notna(x.Buildable):
            _bits.append(f"{x.Buildable:,.0f} sf buildable")
        if pd.notna(x.ROC):
            _bits.append(f"<b>{x.ROC:.0%} ROC</b>")
        if x.get("_breakeven"):
            _bits.append(f"<b>{x['_breakeven']}</b>")
        _head = ""
        if mm:
            _col = {"STRONG": "#1f5c2e", "GOOD": "#1f5c2e", "TIGHT": "#8a5a00",
                    "STRETCH": "#8a5a00", "NO": "#7a2518"}.get(mm["tier"], "#55524a")
            _head = (f'<b style="color:{_col}">{mm["tier"]} · breaks even at '
                     f'${mm["breakeven"]:,}/sf against a market median of '
                     f'${mm["median"]:,} ({mm["margin"]:+.0%})</b><br>')
        st.markdown(f'<div class="{_css}">{sig_stamp(x.Signal)} &nbsp; <b>{x.Address}</b>'
                    f'<br>{_head}<span class="cite">{" · ".join(_bits)}<br>{x.Why}'
                    f'</span></div>', unsafe_allow_html=True)
        render_detail(x, f, a, discount, overrides)

st.markdown("---")

# ---- the short list Tal builds by starring lots as he goes ----
# It lives in the SIDEBAR: with 130+ lot cards on the page, anything rendered below
# them is effectively invisible. The sidebar stays on screen while he scrolls, so the
# basket is always in view and the count updates the moment he stars something.
_internal = [c for c in ["_card","_f","_override","_breakeven","_pf","_verified",
              "_margin","_rank_score","_breakeven_psf","_cliff","_rti"] if c in df.columns]

def _shortlist_exports(sl):
    """Build the two CSVs for the starred lots: the handoff summary and the checklist."""
    out_rows = []
    for _, s in sl.iterrows():
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
    srows = []
    for _, s in sl.iterrows():
        card = s.get("_card")
        if isinstance(card, list) and card:
            srows.extend(card_to_rows(s.Address, card))
    return out_rows, srows


with _sl_slot:
    if shortlist:
        sl = df[df.Address.isin(shortlist)]
        st.markdown(f"### ★ Short list ({len(sl)})")
        for _, s in sl.iterrows():
            mark = " ★" if s.get("_override") else ""
            roc = f"{s.ROC:.0%}" if pd.notna(s.ROC) else s.Signal
            st.markdown(f'<span class="cite"><b>{s.Address}</b><br>{s.Signal} · {roc}{mark}'
                        f'</span>', unsafe_allow_html=True)
        out_rows, srows = _shortlist_exports(sl)
        b1 = io.StringIO(); pd.DataFrame(out_rows).to_csv(b1, index=False)
        st.download_button("Download short list", b1.getvalue(),
                           "short_list.csv", "text/csv", key="dl_sl_side")
        if srows:
            b2 = io.StringIO(); pd.DataFrame(srows).to_csv(b2, index=False)
            st.download_button("Download their checklist", b2.getvalue(),
                               "short_list_diligence.csv", "text/csv", key="dl_slc_side")
        if st.button("Clear short list", key="clr_side"):
            st.session_state["_shortlist"] = set()
            st.rerun()
    else:
        st.markdown("### ★ Short list (0)")
        st.markdown('<span class="cite">Tick the ★ next to any lot and it collects here. '
                    'Stays visible while you scroll.</span>', unsafe_allow_html=True)
    st.markdown("---")

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

st.markdown("---")
st.caption(f"Build {BUILD}")
