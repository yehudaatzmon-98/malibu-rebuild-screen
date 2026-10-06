"""Markdown for two data-room tabs, rebuilt every run from the current workbook (no hand-typed numbers).

  python model_tab.py inputs YYYY-MM-DD  -> "Model inputs & math": every assumption with its source, sale $/sf by
                                            neighborhood, how a lot's numbers are built, and the full cost build-up
                                            for every lot in the screen (the spreadsheet's All Lots columns).
  python model_tab.py plan YYYY-MM-DD    -> "10-lot plan": the lots in data/plan10.txt, the investor/sponsor split
                                            at the base build cost and the two sensitivity costs, and caveats.
"""
import os, sys
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
mode = sys.argv[1]; asof = sys.argv[2] if len(sys.argv) > 2 else ""
wb = openpyxl.load_workbook(os.path.join(HERE, "Palisades_Lot_Screen.xlsx"), data_only=True)
a = wb["Assumptions"]
A, ROWS, NB = {}, [], []
r = 4
while a.cell(r, 1).value:
    k, v, src = a.cell(r, 1).value, a.cell(r, 2).value, a.cell(r, 3).value or ""
    A[k] = v; ROWS.append((k, v, src)); r += 1
for r in range(r, a.max_row + 1):
    if a.cell(r, 1).value == "Code":
        for q in range(r + 1, a.max_row + 1):
            if a.cell(q, 1).value: NB.append((a.cell(q, 1).value, a.cell(q, 2).value, a.cell(q, 3).value or ""))
        break
lt = wb["All Lots"]; h = {lt.cell(2, c).value: c for c in range(1, lt.max_column + 1)}
LOTS = []
for r in range(3, lt.max_row + 1):
    if lt.cell(r, h["Address"]).value:
        LOTS.append({k: lt.cell(r, c).value for k, c in h.items()})
M = lambda x: ("-" if x < 0 else "") + f"${abs(x) / 1e6:.2f}M"; K = lambda x: "–" if not x else (f"${x / 1e6:.2f}M" if x >= 1e6 else f"${x / 1e3:,.0f}K"); D0 = lambda x: f"${x:,.0f}"
esc = lambda s: str(s).replace("|", "/").replace("\n", " ")


def fmt(k, v):
    if isinstance(v, str): return v
    if v is None: return ""
    if "%" in k or "rate" in k.lower() or "commission" in k.lower() or "tax" in k.lower() and v < 1 or "premium over" in k or "Target margin" in k or "loan (%" in k or "drawn" in k or "points" in k:
        if v < 1: return f"{v * 100:g}%"
    if "x old" in k or "x lot" in k: return f"{v:g}x"
    if "yrs" in k: return f"{v:g} years"
    if "max sf" in k: return f"{v:,.0f} sf"
    if v >= 1000 or "$" in k: return D0(v)
    return f"{v:g}"


if mode == "inputs":
    out = ["# Model inputs & math", "",
           f"Updated {asof} from the same model as every other tab. This tab replaces the spreadsheet's Assumptions and All Lots tabs: "
           "the inputs, where each comes from, and the full cost build-up for every lot. It is rebuilt every morning, so it always matches "
           "the numbers elsewhere in the data room. To change an input, tell Yehuda; the next morning's run uses it everywhere.", "",
           "## Inputs", "", "| Input | Value | Where it comes from |", "| --- | --- | --- |"]
    for k, v, src in ROWS:
        if k.startswith("Scenario used"): continue
        out.append(f"| {esc(k)} | {fmt(k, v)} | {esc(src)} |")
    out += ["", "## Sale price per sf by neighborhood", "",
            "Today's comps for a new 4,500–7,000 sf home (the worst case). Medium adds "
            f"{A[chr(77) + 'EDIUM case: premium over today' + chr(39) + 's comps'] * 100:g}%, best adds "
            f"{A['BEST case: premium over today' + chr(39) + 's comps'] * 100:g}%. The evidence behind each is on the Comps tracker tab.", "",
            "| Neighborhood | Sale $/sf (worst case) | Evidence |", "| --- | --- | --- |"]
    for code, v, ev in NB:
        name, _, rest = ev.partition(" · ")
        out.append(f"| {esc(name)} | {D0(v)} | {esc(rest)} |")
    out += ["", "## How each lot's numbers are built", "",
            f"- **House size:** city-approved plans where they exist; otherwise whichever earns more of {A['Fast-track size (x old house)']:g}x the old house "
            f"({A['Fast-track / approved-plans project length (yrs)']:g}-year project) or {A['Build-to-zoning size (x lot area)'] * 100:g}% of lot area up to "
            f"{A['Build-to-zoning max sf']:,.0f} sf ({A['Build-to-zoning project length (yrs)']:g}-year project).",
            f"- **Sale price** = house sf × the neighborhood's $/sf × (1 + scenario premium), plus the ocean-view premium (${A['Ocean-view premium ($/sf added to the neighborhood price)']:,.0f}/sf) "
            f"where the MLS lists an ocean view and the gated premium (${A['Gated-community premium ($/sf added)']:,.0f}/sf) for gated lots.",
            f"- **Construction** = house sf × ${A['Construction cost ($/sf, fixed)']:,.0f}. **Design, permits & fees** = ${A['Design, permits & fees — lots WITHOUT approved plans ($/sf)']:,.0f}/sf, "
            f"or {A['Reserve — lots WITH city-approved plans (% of asking price)'] * 100:g}% of the lot price when plans are approved.",
            f"- **Loan interest & points** = {A['Construction loan (% of cost)'] * 100:g}% × (land + construction + design) × "
            f"({A['Loan rate'] * 100:g}% × years × {A['Avg % of loan drawn'] * 100:g}% average draw + {A['Loan points'] * 100:g} points).",
            f"- **Property tax** = {A['Property tax (% of land / yr)'] * 100:g}% of the lot price per year. **Commission & transfer tax** = "
            f"{A['Sale commission'] * 100:g}% + {A['City + county transfer tax'] * 100:g}% of the sale price.",
            f"- **Measure ULA** = {A['ULA tier 1 rate'] * 100:g}% of the sale price at or above {M(A['ULA tier 1 threshold'])}, {A['ULA tier 2 rate'] * 100:g}% at or above {M(A['ULA tier 2 threshold'])}.",
            f"- **Profit** = sale price − total cost. **Max offer** = the most we can pay for the lot and still earn {A['Target margin (profit ÷ total cost)'] * 100:g}% on total cost in the medium case.",
            "", "## Full cost build-up, every lot (medium case)", "",
            "Sorted by margin. Asking prices from Redfin; 🌊 = MLS lists an ocean view.", "",
            "| Lot | Ask | House sf (basis) | Yrs | Construction | Design / reserve | Loan int. & pts | Prop. tax | Comm. & transfer | ULA | Total cost | Sale price | Profit | Margin | Max offer |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for g in sorted(LOTS, key=lambda g: -(g["Margin (profit ÷ cost)"] or -9)):
        oc = " 🌊" if g.get("Ocean view (MLS)") == "Yes" else ""
        out.append(f"| {g['Address']}{oc} | {M(g['Asking price'])} | {int(g['New house size (sf)']):,} ({g['How sized'].lower()}) | {int(g['Project length (yrs)'])} | "
                   f"{M(g['Construction'])} | {K(g['Design, permits & fees (or 5% reserve)'])} | {K(g['Loan interest & points'])} | {K(g['Property tax'])} | "
                   f"{K(g['Commission & transfer tax'])} | {K(g['Mansion tax (ULA)'])} | {M(g['TOTAL COST'])} | {M(g['Sale price'])} | {M(g['Profit'])} | "
                   f"{round(g['Margin (profit ÷ cost)'] * 100) + 0:.0f}% | {M(max(g['Most we should pay for the lot'], 0))} |")
    out += ["", "Source: Palisades Lot Screen model (Redfin listings, LA County parcel data, LADBS open data); recalculated each morning."]
    # Claude Docs reads two dollar signs in one prose line as a math formula; escape them outside tables
    out = [l if l.startswith("|") or l.count("$") < 2 else l.replace("$", "\\$") for l in out]
    print("\n".join(out))

elif mode == "plan":
    PREF, SPLIT, FEE = 0.08, 0.70, 0.04
    plan = [l.strip() for l in open(os.path.join(D, "plan10.txt")) if l.strip()]
    by = {g["Address"]: g for g in LOTS}
    sel = [by[p] for p in plan if p in by]; missing = [p for p in plan if p not in by]

    def ula(s):
        return A["ULA tier 2 rate"] if s >= A["ULA tier 2 threshold"] else (A["ULA tier 1 rate"] if s >= A["ULA tier 1 threshold"] else 0)

    def calc(g, psf, cost):
        sf, y, ask = g["New house size (sf)"], g["Project length (yrs)"], g["Asking price"]
        sale = sf * psf
        soft = A["Reserve — lots WITH city-approved plans (% of asking price)"] * ask if g["City-approved plans?"] == "Yes" else A["Design, permits & fees — lots WITHOUT approved plans ($/sf)"] * sf
        base = ask + sf * cost + soft
        interest = A["Construction loan (% of cost)"] * base * (A["Loan rate"] * y * A["Avg % of loan drawn"] + A["Loan points"])
        tax = ask * A["Property tax (% of land / yr)"] * y
        tc = base + interest + tax + sale * (A["Sale commission"] + A["City + county transfer tax"] + ula(sale))
        eq = base * (1 - A["Construction loan (% of cost)"]) + interest + tax
        return sale - tc, tc, eq, base - ask

    costs = [A["Construction cost ($/sf, fixed)"], A["Sensitivity: lower build cost A ($/sf)"], A["Sensitivity: lower build cost B ($/sf)"]]
    keys = ["Worst: sale $/sf", "Medium: sale $/sf", "Best: sale $/sf"]
    # self-check against the workbook: medium profit at the base build cost must match
    for g in sel:
        assert abs(calc(g, g["Medium: sale $/sf"], costs[0])[0] - g["Medium: profit"]) < 5, g["Address"]
    rows = []
    for cost in costs:
        res = []
        for k in keys:
            tot = inv = us = 0
            for g in sel:
                p, tc, eq, hard = calc(g, g[k], cost)
                fee = hard * FEE; P = p - fee; pr = eq * PREF * g["Project length (yrs)"]
                tot += p; us += fee
                if P <= pr: inv += P
                else: inv += pr + (P - pr) * SPLIT; us += (P - pr) * (1 - SPLIT)
            res.append((tot, inv, us))
        E = sum(calc(g, g[keys[0]], cost)[2] for g in sel)
        rows.append((cost, E, res))
    yrs = sum(g["Project length (yrs)"] for g in sel) / len(sel)
    out = ["# 10-lot plan (updated daily)", "",
           f"Updated {asof}. Rebuilt every morning from the same model as the All lots tab, so price cuts, lots going pending and new comps flow in automatically. "
           "Working structure after the 10/1 call: one entity, 1–2 larger investors, an 8% preferred return (simple, lot by lot), then 70/30 (investors/us), "
           "plus a 4% developer fee on construction and soft costs, paid either way.", ""]
    if missing:
        out += [f"**Heads up:** no longer in the active listings: {', '.join(missing)}. Numbers below cover the remaining {len(sel)} lots.", ""]
    out += ["## The deal at three build costs", "",
            "| Build cost | Equity needed | Total profit: worst / medium / best | Investors get: worst / medium / best | Investor multiple: worst / medium / best | We get: worst / medium / best |",
            "| --- | --- | --- | --- | --- | --- |"]
    for i, (cost, E, res) in enumerate(rows):
        lab = ["model", "Tal's estimate", "Tal's low case"][i]
        cells = [f"${cost:,.0f}/sf ({lab})", M(E), " / ".join(M(t) for t, _, _ in res), " / ".join(M(v) for _, v, _ in res),
                 " / ".join(f"{(E + v) / E:.2f}x" for _, v, _ in res), " / ".join(M(u) for _, _, u in res)]
        if i == 1: cells = [f"**{c}**" for c in cells]
        out.append("| " + " | ".join(cells) + " |")
    E1, res1 = rows[1][1], rows[1][2]
    out += ["", f"\"We get\" is the fee plus our 30%, for Tal and Yehuda together, before legal and fund costs. Projects average {yrs:.1f} years, so the medium-case "
            f"investor multiple at ${costs[1]:,.0f}/sf is roughly {((E1 + res1[1][1]) / E1 - 1) / yrs * 100:.0f}% a year (simple, not an IRR). "
            "Tal (10/1): about $5M to us in the medium case works; about $2.5M in the worst case is not enough on its own.", "",
            "## The lots", "", f"Land at asking: {M(sum(g['Asking price'] for g in sel))}.", "",
            f"| Lot | Neighborhood | Ask | House sf (basis) | Margin (medium, ${costs[0]:,.0f}) | Profit: medium at ${costs[0]:,.0f} / ${costs[1]:,.0f} / ${costs[2]:,.0f} | Max offer | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for g in sel:
        ps = [calc(g, g[keys[1]], c)[0] for c in costs]
        oc = " 🌊" if g.get("Ocean view (MLS)") == "Yes" else ""
        out.append(f"| {g['Address']}{oc} | {g['Neighborhood']} | {M(g['Asking price'])} | {int(g['New house size (sf)']):,} ({g['How sized'].lower()}) | "
                   f"{g['Margin (profit ÷ cost)'] * 100:.0f}% | {' / '.join(M(p) for p in ps)} | {M(g['Most we should pay for the lot'])} | {esc(g['Notes'] or '')} |")
    below = [g["Address"] for g in sel if g["Margin (profit ÷ cost)"] < A["Target margin (profit ÷ total cost)"]]
    out += ["", "## Caveats", ""]
    if below: out.append(f"- Now below a 15% margin at asking: {', '.join(below)}.")
    out += ["- 824 Chautauqua: lot-line adjustment pending. 627 N Marquette: septic; house size is a zoning estimate. 623 N Marquette: long time on market.",
            "- No Rustic Canyon lot clears 15% at asking yet. 14511 W Sunset stays out until its title and access are checked (Tal's concern).",
            "- Still to confirm: a written build price from contractor Tal, and whether medium-case sale prices hold (Comps tracker).",
            "- The lot list lives in data/plan10.txt; it changes only when Tal or Yehuda change it."]
    print("\n".join(out))
