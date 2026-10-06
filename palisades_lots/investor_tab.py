"""Markdown for the investor data room's generated tabs. Every number comes from deal.py (the current workbook).

  python investor_tab.py lots    YYYY-MM-DD  -> "The ten lots (updated daily)"
  python investor_tab.py numbers YYYY-MM-DD  -> "Project numbers (updated daily)": totals, both financing models, build cost
  python investor_tab.py market  YYYY-MM-DD  -> "Market evidence (updated daily)": closed sales and new homes for sale
  python investor_tab.py inputs  YYYY-MM-DD  -> "Assumptions and method (updated daily)"
No deal terms, no max offers: this is the outside-facing room.
"""
import csv, os, sys
from deal import A, LOTS, PLAN, COSTS, CASES, calc, portfolio, selfcheck

HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
mode, asof = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
selfcheck()
M = lambda x: ("-" if x < 0 else "") + f"${abs(x) / 1e6:.2f}M"
M1 = lambda x: ("-" if x < 0 else "") + f"${abs(x) / 1e6:.1f}M"
K = lambda x: "–" if not x else (M(x) if abs(x) >= 1e6 else f"${x / 1e3:,.0f}K")
D0 = lambda x: f"${x:,.0f}"
P = lambda x: f"{x * 100:.0f}%"
NOTES = {r["address"]: r["note"] for r in csv.DictReader(open(os.path.join(D, "investor_notes.csv")))}
SEL = [a for a in PLAN if a in LOTS]
GONE = [a for a in PLAN if a not in LOTS]
FIN = {"loan": "A · one loan for land and build", "cash": "B · land in cash, loan to build"}
SHORT = {"Bluffs / El Medio": "Bluffs"}


def basis(g):
    h = g["How sized"]
    return {"Approved plans": "city-approved plans", "110% old house": "like-for-like rebuild at 110%",
            "Zoning estimate": "estimate from lot area", "Listing claim": "listing's plans (not yet verified)"}.get(h, h.lower())


def out(lines):
    # Claude Docs reads two dollar signs in one prose line as math; escape them outside tables
    print("\n".join(l if l.startswith("|") or l.count("$") < 2 else l.replace("$", "\\$") for l in lines))


head = lambda title, blurb: [f"# {title}", "", f"Updated {asof}. {blurb}", ""]

if mode == "lots":
    L = head("The ten lots", "Rebuilt every morning from the current listings and closed sales, so price cuts and new sales show up here automatically. "
             f"Construction at ${COSTS[0]:,.0f}/sf. Worst case = homes sell at today's prices; medium = 10% more for a brand-new home; best = 20% more.")
    if GONE:
        L += [f"**Note:** no longer in the active listings: {', '.join(GONE)}. Totals cover the remaining {len(SEL)} lots.", ""]
    L += ["## At a glance", "",
          "| Lot | Area | Asking | New home | Sale (medium) | Profit: worst / medium / best | Margin (medium) |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for a in SEL:
        g = LOTS[a]; w, m, b = (calc(g, c) for c, _ in CASES)
        L.append(f"| {a} | {SHORT.get(g['Neighborhood'], g['Neighborhood'])} | {D0(g['Asking price'])} | {int(m['sf']):,} sf, {basis(g)} | {M(m['sale'])} | "
                 f"{M(w['profit'])} / {M(m['profit'])} / {M(b['profit'])} | {P(m['margin'])} |")
    t = [portfolio(SEL, c) for c, _ in CASES]
    L.append(f"| **All {len(SEL)}** | | **{M1(t[0]['land'])}** | | **{M1(t[1]['sale'])}** | **{M1(t[0]['profit'])} / {M1(t[1]['profit'])} / {M1(t[2]['profit'])}** | **{P(t[1]['margin'])}** |")
    L += ["", "Margin = profit ÷ total cost. Figures are for the project, before any split between investors and sponsors. Financing A (one loan for land and build); "
          "the Project numbers tab shows financing B and lower build costs.", ""]
    for a in SEL:
        g = LOTS[a]; r = {c: calc(g, c) for c, _ in CASES}; m = r["Medium"]
        mb = calc(g, "Medium", fin="cash"); m650 = calc(g, "Medium", COSTS[1])
        L += [f"## {a} · {g['Neighborhood']}", "",
              f"Asking {D0(g['Asking price'])} · lot {int(g['Lot size (sf)']):,} sf · new home {int(m['sf']):,} sf ({basis(g)}) · about {int(m['years'])} years from purchase to sale.", "",
              NOTES.get(a, g.get("Notes") or ""), "",
              "| | Worst | Medium | Best |", "| --- | --- | --- | --- |",
              "| Sale price per sf | " + " | ".join(D0(r[c]["psf"]) for c, _ in CASES) + " |",
              "| Sale price | " + " | ".join(M(r[c]["sale"]) for c, _ in CASES) + " |",
              f"| Land | {M(m['land'])} | {M(m['land'])} | {M(m['land'])} |",
              f"| Construction ({int(m['sf']):,} sf × ${COSTS[0]:,.0f}) | {M(m['construction'])} | {M(m['construction'])} | {M(m['construction'])} |",
              f"| {'Reserve (5% of lot, plans approved)' if g['City-approved plans?'] == 'Yes' else 'Design, permits and fees'} | {K(m['design'])} | {K(m['design'])} | {K(m['design'])} |",
              f"| Loan interest and points | {K(m['interest'])} | {K(m['interest'])} | {K(m['interest'])} |",
              f"| Property tax | {K(m['tax'])} | {K(m['tax'])} | {K(m['tax'])} |",
              "| Commission and transfer tax | " + " | ".join(K(r[c]["comm"]) for c, _ in CASES) + " |",
              "| ULA transfer tax | " + " | ".join(K(r[c]["ula"]) for c, _ in CASES) + " |",
              "| **Total cost** | " + " | ".join(f"**{M(r[c]['total'])}**" for c, _ in CASES) + " |",
              "| **Profit** | " + " | ".join(f"**{M(r[c]['profit'])}**" for c, _ in CASES) + " |",
              "| Margin | " + " | ".join(P(r[c]["margin"]) for c, _ in CASES) + " |", "",
              f"Cash needed: {M(m['cash_in'])} with one loan for land and build, {M(mb['cash_in'])} with the land bought in cash "
              f"(medium-case profit {M(mb['profit'])}). At ${COSTS[1]:,.0f}/sf construction, medium-case profit is {M(m650['profit'])}.", ""]
    L += ["Sources: Redfin listings; LA County Assessor; LADBS permit records; listing claims are the sellers' words unless marked as checked with the city."]
    out(L)

elif mode == "numbers":
    L = head("Project numbers", "All ten lots together, rebuilt every morning from the same model as the lot pages. Project-level figures, before any split between investors and sponsors.")
    for fin in ("loan", "cash"):
        t = [portfolio(SEL, c, fin=fin) for c, _ in CASES]
        L += [f"## Financing {FIN[fin]}", "",
              ("A construction loan for 65% of total cost (land, construction and design), closed with the purchase." if fin == "loan" else
               "The land is bought outright. The construction loan covers construction and design only, up to 65% of total cost. Smaller loan, less interest, more cash in. "
               "A combined purchase and construction loan takes about two months per lot to close and is harder to get early on, so the first lots will likely be bought this way."), "",
              f"| All {len(SEL)} lots, construction ${COSTS[0]:,.0f}/sf | Worst | Medium | Best |", "| --- | --- | --- | --- |"]
        rows = [("Land (asking prices)", "land"), ("Construction and design", None), ("Loan interest and points", "interest"), ("Property tax", "tax"),
                ("Commission and transfer tax", "comm"), ("ULA transfer tax", "ula"), ("**Total cost**", "total"), ("Home sales", "sale"), ("**Profit**", "profit")]
        for lab, k in rows:
            vals = [x["construction"] + x["design"] if k is None else x[k] for x in t]
            L.append(f"| {lab} | " + " | ".join((f"**{M1(v)}**" if lab.startswith("**") else M1(v)) for v in vals) + " |")
        L += ["| Margin on total cost | " + " | ".join(P(x["margin"]) for x in t) + " |",
              f"| Loan | {M1(t[0]['loan'])} | {M1(t[1]['loan'])} | {M1(t[2]['loan'])} |",
              f"| Cash needed | {M1(t[0]['cash_in'])} | {M1(t[1]['cash_in'])} | {M1(t[2]['cash_in'])} |",
              "| Profit ÷ cash needed (whole project) | " + " | ".join(P(x["roc"]) for x in t) + " |", ""]
    L += ["## If construction comes in lower", "", "Medium-case profit (worst case in brackets) at three construction costs. $650/sf is Tal's estimate; $600/sf is what local builders are reported to deliver (secondhand, not verified).", "",
          "| Construction cost | A: cash needed | A: profit | B: cash needed | B: profit |", "| --- | --- | --- | --- | --- |"]
    for cost in COSTS:
        a_ = [portfolio(SEL, c, cost, "loan") for c in ("Worst", "Medium")]; b_ = [portfolio(SEL, c, cost, "cash") for c in ("Worst", "Medium")]
        L.append(f"| ${cost:,.0f}/sf | {M1(a_[1]['cash_in'])} | {M1(a_[1]['profit'])} ({M1(a_[0]['profit'])}), {P(a_[1]['margin'])} | {M1(b_[1]['cash_in'])} | {M1(b_[1]['profit'])} ({M1(b_[0]['profit'])}), {P(b_[1]['margin'])} |")
    yrs = portfolio(SEL)["years"]
    L += ["", f"Projects average {yrs:.1f} years from purchase to sale. \"Profit ÷ cash needed\" is over the whole project, not per year."]
    out(L)

elif mode == "market":
    nb = {r["code"]: r for r in csv.DictReader(open(os.path.join(D, "nbhd_base.csv")))}
    comps = [r for r in csv.DictReader(open(os.path.join(D, "comps_log.csv"))) if r["qualifies"] == "Y"]
    names = {"RIV": "Riviera", "HUNT": "Huntington Palisades", "BLUFF": "Bluffs / El Medio"}
    L = head("Market evidence", "What newer homes have actually sold for in the three neighborhoods where the ten lots are, plus the brand-new homes now for sale. "
             "A sale counts if it is a house in 90272 built 2010 or later, 2,000+ sf, closed in the last 24 months, and not a burned house sold as land.")
    L += ["## The price per sf each neighborhood uses", "", "| Neighborhood | Today's price (worst case) | Medium (+10%) | Best (+20%) | How it was set |", "| --- | --- | --- | --- | --- |"]
    for code in ("RIV", "HUNT", "BLUFF"):
        r = nb[code]; v = float(r["applied_psf"])
        how = (f"Median of {r['rule_n']} qualifying sales" if r["status"].startswith("rule") else
               f"Judgment from {r['rule_n']} qualifying sale(s) (median ${float(r['rule_psf']):,.0f}) and new-home asking prices" if r["rule_n"] not in ("", "0") else "Judgment; no qualifying sales yet")
        L.append(f"| {names[code]} | ${v:,.0f} | ${v * 1.1:,.0f} | ${v * 1.2:,.0f} | {how} |")
    L += ["", "Lots whose MLS listing shows an ocean view add $100/sf to these.", "", "## Qualifying sales in these neighborhoods", "",
          "| Closed | Address | Neighborhood | Built | Size | Price | Per sf |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted([c for c in comps if c["nbhd"] in names], key=lambda r: r["sold_date"], reverse=True):
        L.append(f"| {r['sold_date']} | {r['address']} | {names[r['nbhd']]} | {int(float(r['year_built']))} | {int(float(r['sqft'])):,} sf | {M(float(r['price']))} | ${int(float(r['psf'])):,} |")
    L += ["", "## Brand-new homes for sale (asking prices, not sales)", "", "| Address | Area | Asking | Size | Asking per sf | Status |", "| --- | --- | --- | --- | --- | --- |"]
    for r in csv.DictReader(open(os.path.join(D, "asking_newbuilds.csv"))):
        a_, s_ = float(r["asking"]), float(r["sqft"])
        L.append(f"| {r['address']} | {r['neighborhood']} | {M(a_)} | {int(s_):,} sf | ${a_ / s_:,.0f} | {r['status'].split(';')[0]} |")
    L += ["", "## What happened after other fires", "",
          "| Fire | What prices did | Source |", "| --- | --- | --- |",
          "| Woolsey, Malibu (2018) | $/sf up 5% inside the burn area vs. 27% outside over 3 years | [Redfin](https://www.redfin.com/news/california-wildfire-housing-market-impact/) |",
          "| Tubbs, Santa Rosa (2017) | $/sf up 25% inside vs. 35% outside over 3 years | [Redfin](https://www.redfin.com/news/california-wildfire-housing-market-impact/) |",
          "| Eaton, Altadena (2025) | 3245 Arrowhead Ct rebuild listed at about $1.9M, closed 6/17/2026 at $1.6M | [Compass](https://www.compass.com/homedetails/3245-Arrowhead-Ct-Altadena-CA-91001/1KO7GK_pid/) |",
          "| California fires 2001–2015 | Burned areas gained 2–6% vs. neighbors over 1–4 years, peaking around year 3 | [Issler et al., UC Berkeley](https://faculty.haas.berkeley.edu/stanton/pdf/fire.pdf) |", "",
          "That is why the worst case assumes no premium for a new home. Sales data: Redfin, Homes.com and Compass records, still to be confirmed against MLS and title."]
    out(L)

elif mode == "inputs":
    L = head("Assumptions and method", "Every input the model uses and where it comes from. The same inputs drive every number in this data room.")
    fmt = {"%": lambda v: f"{v * 100:g}%", "$": lambda v: D0(v), "x": lambda v: f"{v:g}x", "y": lambda v: f"{v:g} years", "sf": lambda v: f"{v:,.0f} sf"}
    rows = [("Construction", "Construction cost ($/sf, fixed)", "$", "Builder's quoted price, fixed in the model"),
            ("Design, permits and fees (no approved plans)", "Design, permits & fees — lots WITHOUT approved plans ($/sf)", "$", "Per sf of house; placeholder until architect quotes"),
            ("Reserve when plans are approved", "Reserve — lots WITH city-approved plans (% of asking price)", "%", "Share of the lot price, replacing design costs"),
            ("Construction loan", "Construction loan (% of cost)", "%", "Share of cost; to confirm with a lender"),
            ("Loan rate", "Loan rate", "%", "Placeholder"), ("Loan points", "Loan points", "%", "Placeholder"),
            ("Average share of loan drawn", "Avg % of loan drawn", "%", "Loans are drawn as the house is built"),
            ("Property tax", "Property tax (% of land / yr)", "%", "About 1.2% of the purchase price per year"),
            ("Sale commission", "Sale commission", "%", "Tal lists the homes; includes the buyer's agent"),
            ("City and county transfer tax", "City + county transfer tax", "%", "LA City 0.45% + County 0.11%"),
            ("ULA tax, sales at or above tier 1", "ULA tier 1 rate", "%", f"Sales of {M(A['ULA tier 1 threshold'])} or more (Measure ULA)"),
            ("ULA tax, sales at or above tier 2", "ULA tier 2 rate", "%", f"Sales of {M(A['ULA tier 2 threshold'])} or more"),
            ("Like-for-like rebuild size", "Fast-track size (x old house)", "x", "City Executive Order 1 fast track"),
            ("House size without plans", "Build-to-zoning size (x lot area)", "x", "Share of lot area; an architect must confirm"),
            ("Largest house assumed", "Build-to-zoning max sf", "sf", "Keeps homes a sellable size"),
            ("Project length, plans or rebuild", "Fast-track / approved-plans project length (yrs)", "y", "Building starts right after purchase"),
            ("Project length, design needed", "Build-to-zoning project length (yrs)", "y", "Adds a year for design and plan check"),
            ("Ocean-view premium", "Ocean-view premium ($/sf added to the neighborhood price)", "$", "Per sf, where the MLS listing shows an ocean view"),
            ("Medium case", "MEDIUM case: premium over today's comps", "%", "Over today's prices, for a brand-new home"),
            ("Best case", "BEST case: premium over today's comps", "%", "Over today's prices, as the neighborhood recovers"),
            ("Target margin", "Target margin (profit ÷ total cost)", "%", "Profit on total cost a lot must clear at asking")]
    L += ["| Input | Value | Note |", "| --- | --- | --- |"]
    for lab, key, f, note in rows:
        L.append(f"| {lab} | {fmt[f](A[key])}{'/sf' if f == '$' and '$/sf' in key else ''} | {note} |")
    L += ["", "## How each lot's numbers are built", "",
          "- **House size:** the city-approved plans where they exist; otherwise a like-for-like rebuild at 110% of the old home, or an estimate from lot area, whichever earns more.",
          "- **Sale price:** house size × the neighborhood's price per sf (Market evidence tab) × the case's premium, plus the ocean-view premium where it applies.",
          "- **Total cost:** land at asking + construction + design or reserve + loan interest and points + property tax + commission and transfer tax + ULA tax.",
          "- **Profit** = sale price − total cost. **Margin** = profit ÷ total cost.",
          "- **Financing A:** the loan is 65% of land + construction + design. **Financing B:** the land is bought in cash and the loan covers construction and design only, up to 65% of total cost.",
          "- **Cash needed** = everything not covered by the loan, plus loan interest and property tax.", "",
          "Loan terms, design costs and house-size estimates are placeholders until confirmed with a lender, an architect and the builder."]
    out(L)
