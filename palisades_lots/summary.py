"""Print the shortlisted lots and portfolio totals from the recalculated workbook (JSON)."""
import json, os, openpyxl
HERE = os.path.dirname(os.path.abspath(__file__))
ws = openpyxl.load_workbook(os.path.join(HERE, "Palisades_Lot_Screen.xlsx"), data_only=True)["All Lots"]
hdr = {ws.cell(2, c).value: c for c in range(1, ws.max_column + 1)}
short = [l.strip() for l in open(os.path.join(HERE, "data", "short.txt")) if l.strip()]
out, tot = {}, dict(land=0, eq=0, pw=0, pm=0, pb=0)
for r in range(3, ws.max_row + 1):
    a = ws.cell(r, hdr["Address"]).value
    if a not in short: continue
    g = lambda h: ws.cell(r, hdr[h]).value or 0
    eq = (g("Land") + g("Construction") + g("Design, permits & fees (or 5% reserve)")) * 0.35 + g("Loan interest & points") + g("Property tax")
    out[a] = dict(sale_psf=g("Sale price per sf"), sale=round(g("Sale price")), total_cost=round(g("TOTAL COST")), profit=round(g("Profit")),
                  margin=round(g("Margin (profit ÷ cost)"), 3), max_offer=round(g("Most we should pay for the lot")),
                  worst_psf=g("Worst: sale $/sf"), worst_profit=round(g("Worst: profit")), best_psf=g("Best: sale $/sf"), best_profit=round(g("Best: profit")), equity=round(eq))
    tot["land"] += g("Land"); tot["eq"] += eq; tot["pw"] += g("Worst: profit"); tot["pm"] += g("Medium: profit"); tot["pb"] += g("Best: profit")
tot = {k: round(v) for k, v in tot.items()}
tot.update({f"mult_{s}": round((tot["eq"] + tot[f"p{s}"]) / tot["eq"], 2) for s in "wmb"})
print(json.dumps(dict(lots=out, totals=tot), indent=1))
