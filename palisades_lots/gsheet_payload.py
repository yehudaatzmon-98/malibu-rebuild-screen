"""2D arrays for the Google Sheet '02 Lots and numbers' (investor data room on Drive).
python gsheet_payload.py <tab> YYYY-MM-DD  -> JSON 2D array for update_formulas, starting at A1 (Calc/Summary/Lot breakdown: see notes)
Tabs whose data change daily: lots, market, readme (date), inputs (neighborhood prices). Formula tabs are written once."""
import csv, json, os, sys
from deal import A, LOTS, PLAN, COSTS
HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
tab, asof = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
SEL = [a for a in PLAN if a in LOTS]
NOTES = {r["address"]: r["note"] for r in csv.DictReader(open(os.path.join(D, "investor_notes.csv")))}
nbc = {r["code"]: r for r in csv.DictReader(open(os.path.join(D, "nbhd_base.csv")))}
CODE = {"Riviera": "RIV", "Huntington": "HUNT", "Bluffs / El Medio": "BLUFF"}
basis = {"Approved plans": "City-approved plans", "110% old house": "Like-for-like rebuild at 110%", "Zoning estimate": "Estimate from lot area"}
out = []
if tab == "readme":
    out = [["Rebuilding the Palisades: lots and numbers"],
           [f"Updated {asof}. Project-level figures for the ten lots, before any split between investors and sponsors. A discussion draft, not an offer to sell securities."],
           [""], ["How to use it"],
           ["Summary: the ten lots and the project totals. Lot breakdown: every cost line for each lot. Calc: every lot in every case, build cost and financing (use the filter)."],
           ["Blue cells on Inputs and Lots drive everything: change one and every number recalculates. Market evidence holds the closed sales and new homes for sale."],
           [""], ["The cases"],
           ["Worst: no premium for a new home over the price each neighborhood uses (Inputs). Medium: +10%. Best: +20%."],
           ["Closed-sale medians: each neighborhood priced at the median of its recent qualifying closed sales instead, which is lower than the price used in the Bluffs and Huntington."],
           [""], ["Financing"],
           ["A: one construction loan for 65% of land + construction + design, closed with the purchase."],
           ["B: land bought with cash; the loan covers construction and design only, up to 65% of total cost."],
           [""], ["Still to confirm: the builder's $700/sf as a fixed price in writing; loan terms; house sizes on lots without plans (architect); closed sales against title; that approved plans transfer with each sale."],
           ["Sources: listings from Redfin; closed sales from an MLS export plus Redfin and Compass records; LA County Assessor; LADBS permit records. Listing claims are the sellers' words unless marked as checked with the city."]]
elif tab == "inputs":
    rows = [("Construction cost ($/sf)", COSTS[0], "Builder's quote; not yet fixed in writing; a second bid is being sought"),
            ("Lower build cost scenario 1 ($/sf)", COSTS[1], "Our estimate"),
            ("Lower build cost scenario 2 ($/sf)", COSTS[2], "Local wood-frame price, shown for reference (secondhand, not verified); we build in steel"),
            ("Design, permits and fees ($/sf, no approved plans)", A["Design, permits & fees — lots WITHOUT approved plans ($/sf)"], "Placeholder until architect quotes"),
            ("Reserve when plans are approved (% of lot price)", A["Reserve — lots WITH city-approved plans (% of asking price)"], "Replaces design costs"),
            ("Construction loan (% of cost)", A["Construction loan (% of cost)"], "To confirm with a lender"),
            ("Loan rate", A["Loan rate"], "Placeholder"), ("Loan points", A["Loan points"], "Placeholder"),
            ("Average share of loan drawn", A["Avg % of loan drawn"], "Loans are drawn as the house is built"),
            ("Property tax (% of lot price per year)", A["Property tax (% of land / yr)"], "About 1.2% of purchase price"),
            ("Sale commission", A["Sale commission"], "Tal lists the homes; includes the buyer's agent"),
            ("City + county transfer tax", A["City + county transfer tax"], "LA City 0.45% + County 0.11%"),
            ("ULA tier 1 threshold", A["ULA tier 1 threshold"], "Measure ULA"), ("ULA tier 1 rate", A["ULA tier 1 rate"], "Measure ULA"),
            ("ULA tier 2 threshold", A["ULA tier 2 threshold"], "Measure ULA"), ("ULA tier 2 rate", A["ULA tier 2 rate"], "Measure ULA"),
            ("Ocean-view premium ($/sf)", A["Ocean-view premium ($/sf added to the neighborhood price)"], "Where the MLS listing shows an ocean view"),
            ("Medium case premium", A["MEDIUM case: premium over today's comps"], "For a brand-new home"),
            ("Best case premium", A["BEST case: premium over today's comps"], "As the neighborhood recovers")]
    out = [["Inputs (blue cells drive every number in the workbook)"], [""], ["Input", "Value", "Note"]] + [[a, b, c] for a, b, c in rows]
    out += [[""], ["Sale price per sf by neighborhood"], ["Neighborhood", "Price used ($/sf)", "Closed-sale median ($/sf)", "How the price was set"]]
    for nb, code in CODE.items():
        r = nbc[code]; med = float(r["rule_psf"]) if r["rule_n"] not in ("", "0") else float(r["applied_psf"])
        out.append([nb, float(r["applied_psf"]), med, f"Median of {r['rule_n']} qualifying sales" if r["status"].startswith("rule") else f"Judgment, above the median of {r['rule_n']} qualifying sales"])
elif tab == "lots":
    out = [[f"The ten lots (asking prices and facts as of {asof}; blue cells are inputs)"], [""],
           ["Lot", "Neighborhood", "Asking price", "Lot size (sf)", "New house (sf)", "How sized", "Years, purchase to sale", "City-approved plans?", "Ocean view (MLS)?", "Facts"]]
    for a in SEL:
        g = LOTS[a]
        out.append([a, g["Neighborhood"], g["Asking price"], g["Lot size (sf)"], g["New house size (sf)"], basis.get(g["How sized"], g["How sized"]),
                    g["Project length (yrs)"], g["City-approved plans?"], g.get("Ocean view (MLS)") or "No", NOTES.get(a, "")])
elif tab == "market":
    names = {"RIV": "Riviera", "HUNT": "Huntington", "BLUFF": "Bluffs / El Medio"}
    out = [["Closed sales and new homes for sale"], ["A sale counts if it is a house in 90272 built 2010 or later, 2,000+ sf, closed in the last 24 months, and not a burned house sold as land."], [""],
           ["Closed", "Address", "Neighborhood", "Built", "Size (sf)", "Price", "Per sf"]]
    comps = sorted([x for x in csv.DictReader(open(os.path.join(D, "comps_log.csv"))) if x["qualifies"] == "Y" and x["nbhd"] in names], key=lambda x: x["sold_date"], reverse=True)
    for x in comps:
        r = len(out) + 1
        out.append([x["sold_date"], x["address"], names[x["nbhd"]], int(float(x["year_built"])), int(float(x["sqft"])), float(x["price"]), f"=F{r}/E{r}"])
    out += [[""], ["Brand-new homes for sale (asking prices, not sales)"], ["Address", "Area", "Asking", "Size (sf)", "Asking per sf", "Status"]]
    for x in csv.DictReader(open(os.path.join(D, "asking_newbuilds.csv"))):
        r = len(out) + 1
        out.append([x["address"], x["neighborhood"], float(x["asking"]), float(x["sqft"]), f"=C{r}/D{r}", x["status"]])
    out += [[""], ["What happened after other fires"], ["Fire", "What prices did", "Source"],
            ["Woolsey, Malibu (2018)", "$/sf up 5% inside the burn area vs. 27% outside over 3 years; 29 homes rebuilt and none listed at 30 months", "Redfin; Malibu Times"],
            ["Tubbs, Santa Rosa (2017)", "$/sf up 25% inside vs. 35% outside over 3 years", "Redfin"],
            ["Eaton, Altadena (2025)", "3245 Arrowhead Ct rebuild listed at about $1.9M, closed 6/17/2026 at $1.6M; a local developer estimates new homes sell about 20% below no-fire value", "Compass; Homes.com"],
            ["California fires 2001–2015", "Burned areas gained 2–6% vs. neighbors over 1–4 years, peaking around year 3", "Issler et al., UC Berkeley"],
            [""], ["Across 90272, the median price per sf is down about 17% from a year earlier (Redfin, Aug 2026)."]]
print(json.dumps(out, ensure_ascii=False))
