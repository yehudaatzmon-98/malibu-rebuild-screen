"""Regenerate the number blocks of each shortlisted lot's data-room tab from the current workbook.

  python shortlist_md.py            -> JSON {address: {lead_phrase, max_offer, house_line, cost_table, scenarios_table}}
  python shortlist_md.py --overview -> JSON {shortlist_rows: [...], portfolio: {...}}

Use these to replace the matching blocks (read each tab's outline first; replace tables whole).
"""
import json, os, sys
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ws = openpyxl.load_workbook(os.path.join(HERE, "Palisades_Lot_Screen.xlsx"), data_only=True)
a = ws["Assumptions"]
A = {a.cell(r, 1).value: a.cell(r, 2).value for r in range(4, 60) if a.cell(r, 1).value}
lt = ws["All Lots"]
h = {lt.cell(2, c).value: c for c in range(1, lt.max_column + 1)}
short = [l.strip() for l in open(os.path.join(HERE, "data", "short.txt")) if l.strip()]
M = lambda x: f"${x / 1e6:.2f}M"; D = lambda x: f"${x:,.0f}"
COMM = A["Sale commission"]; BC = A["Construction cost ($/sf, fixed)"]


def row(addr):
    for r in range(3, lt.max_row + 1):
        if lt.cell(r, h["Address"]).value == addr:
            return {k: lt.cell(r, c).value for k, c in h.items()}


out, ov = {}, []
tot = dict(land=0, cs=0, sw=0, sm=0, sb=0, cw=0, cm=0, cb=0, pw=0, pm=0, pb=0, eq=0)
for addr in short:
    g = row(addr)
    J = g["New house size (sf)"]
    sw, sb = g["Worst: sale $/sf"] * J, g["Best: sale $/sf"] * J
    cw, cb = sw - g["Worst: profit"], sb - g["Best: profit"]
    eq = (g["Land"] + g["Construction"] + g["Design, permits & fees (or 5% reserve)"]) * 0.35 + g["Loan interest & points"] + g["Property tax"]
    reserve = "5% reserve (approved plans)" if g["City-approved plans?"] == "Yes" else "Design, permits and fees ($75/sf)"
    ocean = g.get("Ocean view (MLS)") == "Yes"
    out[addr] = dict(
        lead_phrase=f"{M(g['Profit'])} ({g['Margin (profit ÷ cost)'] * 100:.0f}% margin) in the medium case and {M(g['Worst: profit'])} at today's comps",
        max_offer=f"**Max offer: {M(g['Most we should pay for the lot'])}** (the most we can pay and still earn 15% on total cost in the medium case). Asking is {g['Asking price'] / g['Most we should pay for the lot'] * 100:.0f}% of that.",
        house_line=f"House {int(J):,} sf ({g['How sized'].lower()}), {int(g['Project length (yrs)'])}-year project, sale at ${g['Sale price per sf']:,.0f}/sf" + (" (includes the ocean-view premium)." if ocean else "."),
        cost_table="\n".join(["| Line | Amount |", "| --- | --- |",
            f"| Land (asking) | {D(g['Land'])} |", f"| Construction ({int(J):,} sf x ${BC:,.0f}) | {D(g['Construction'])} |",
            f"| {reserve} | {D(g['Design, permits & fees (or 5% reserve)'])} |", f"| Loan interest and points | {D(g['Loan interest & points'])} |",
            f"| Property tax | {D(g['Property tax'])} |", f"| Commission ({COMM * 100:.1f}%) and transfer tax | {D(g['Commission & transfer tax'])} |",
            f"| Measure ULA | {D(g['Mansion tax (ULA)'])} |", f"| **Total cost** | **{D(g['TOTAL COST'])}** |", f"| **Sale price** | **{D(g['Sale price'])}** |",
            f"| **Profit** | **{D(g['Profit'])}** ({g['Margin (profit ÷ cost)'] * 100:.1f}%) |", f"| Equity needed | {D(eq)} |", f"| Construction loan (65%) | {D(g['Loan amount'])} |"]),
        scenarios_table="\n".join(["| Scenario | Sale $/sf | Sale price | Total cost | Profit | Margin |", "| --- | --- | --- | --- | --- | --- |",
            f"| Worst (today's comps) | ${g['Worst: sale $/sf']:,.0f} | {M(sw)} | {M(cw)} | {M(g['Worst: profit'])} | {g['Worst: profit'] / cw * 100:.0f}% |",
            f"| Medium (+10%) | ${g['Medium: sale $/sf']:,.0f} | {M(g['Sale price'])} | {M(g['TOTAL COST'])} | {M(g['Medium: profit'])} | {g['Margin (profit ÷ cost)'] * 100:.0f}% |",
            f"| Best (+20%) | ${g['Best: sale $/sf']:,.0f} | {M(sb)} | {M(cb)} | {M(g['Best: profit'])} | {g['Best: profit'] / cb * 100:.0f}% |"]),
        build_cost_sensitivity=f"Medium-case profit if construction comes in at ${A['Sensitivity: lower build cost A ($/sf)']:,.0f}/sf: {M(g['Medium profit if build cost = A'])}; at ${A['Sensitivity: lower build cost B ($/sf)']:,.0f}/sf: {M(g['Medium profit if build cost = B'])}.",
        shortlist_row=dict(sale=M(g["Sale price"]), profits=f"{g['Worst: profit'] / 1e6:.2f} / {g['Medium: profit'] / 1e6:.2f} / {g['Best: profit'] / 1e6:.2f}", max_offer=M(g["Most we should pay for the lot"])))
    for k, v in dict(land=g["Land"], cs=g["Construction"] + g["Design, permits & fees (or 5% reserve)"], sw=sw, sm=g["Sale price"], sb=sb, cw=cw,
                     cm=g["TOTAL COST"], cb=cb, pw=g["Worst: profit"], pm=g["Medium: profit"], pb=g["Best: profit"], eq=eq).items():
        tot[k] += v
port = {k: f"${v / 1e6:.1f}M" for k, v in tot.items()}
for s in "wmb":
    port[f"mult_{s}"] = f"{(tot['eq'] + tot['p' + s]) / tot['eq']:.2f}x"
if "--overview" in sys.argv:
    print(json.dumps(dict(shortlist={k: v["shortlist_row"] for k, v in out.items()}, portfolio=port), indent=1))
else:
    print(json.dumps(out, indent=1))
