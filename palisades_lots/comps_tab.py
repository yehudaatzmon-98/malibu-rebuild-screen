"""Markdown for the data room's "Comps tracker" tab, built from data/. Usage: python comps_tab.py YYYY-MM-DD"""
import csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
asof = sys.argv[1] if len(sys.argv) > 1 else ""
NB = {"RIV": "Riviera", "HUNT": "Huntington", "RUSTIC": "Rustic Canyon", "BLUFF": "Bluffs / El Medio", "VDLP": "Via de la Paz",
      "ALPHA": "Alphabet / Village", "MK": "Marquez Knolls", "UPS": "Upper Las Lomas / Las Pulgas", "RIDGE": "Ridgeview",
      "CAST": "Castellammare", "ENC": "The Enclave", "HIGH": "Highlands", "SUMMIT": "The Summit"}
base = list(csv.DictReader(open(os.path.join(D, "nbhd_base.csv"))))
log = [r for r in csv.DictReader(open(os.path.join(D, "comps_log.csv"))) if r["qualifies"] == "Y"]
ask = list(csv.DictReader(open(os.path.join(D, "asking_newbuilds.csv"))))
m = lambda v: f"${int(round(float(v))):,}"

out = [f"# Comps tracker", "",
       f"Updated {asof}. The model's sale price per sf for each neighborhood comes from closed sales of houses built 2010 or later. "
       f"{len(log)} sales qualify today. New sales are added every week and the model and lot pages are updated to match.", "",
       "## Sale price per sf used in the model (worst case)", "",
       "| Neighborhood | $/sf used | Where it comes from | Qualifying sales | Their median |", "| --- | --- | --- | --- | --- |"]
for b in base:
    used = b["override_psf"] or b["applied_psf"]
    src = "Override" if b["override_psf"] else ("Median of closed sales" if b["status"].startswith("rule") else "Judgment (too few sales, or sales disagree)")
    out.append(f"| {NB.get(b['code'], b['code'])} | {m(used)} | {src} | {b['rule_n'] or 0} | {m(b['rule_psf']) if b['rule_psf'] else '-'} |")
flags = [b for b in base if not b["override_psf"] and int(b["rule_n"] or 0) >= 3 and not b["status"].startswith("rule")]
if flags:
    out += ["", "**Needs a decision:** " + "; ".join(
        f"{NB[b['code']]} closed sales point to {m(b['rule_psf'])}/sf vs {m(b['judgment_psf'])} in the model" for b in flags) +
        ". The model keeps the current value until Tal sets an override."]
out += ["", "## Qualifying closed sales", "", "| Sold | Address | Neighborhood (auto-matched) | Price | Sf | $/sf | Built |", "| --- | --- | --- | --- | --- | --- | --- |"]
for r in log:
    addr = f"[{r['address']}]({r['url']})" if r["url"] else r["address"]
    out.append(f"| {r['sold_date']} | {addr} | {NB.get(r['nbhd'], r['nbhd'])} | {m(r['price'])} | {int(float(r['sqft'])):,} | {m(r['psf'])} | {int(float(r['year_built']))} |")
out += ["", "## New builds for sale (asking, not sold)", "", "| Address | Neighborhood | Asking | Sf | $/sf | Status |", "| --- | --- | --- | --- | --- | --- |"]
for r in ask:
    out.append(f"| {r['address']} | {r['neighborhood']} | {m(r['asking'])} | {int(float(r['sqft'])):,} | {m(float(r['asking']) / float(r['sqft']))} | {r['status']} |")
out += ["", "How it works:",
        "- A sale counts when it is a house in 90272 closed in the last 24 months, 2,000+ sf, built 2010 or later, and not a burned house sold as a lot (LA County damage data).",
        "- Each sale is matched to the neighborhood of the nearest lots on our list, so a sale near a border can land in the wrong one. A neighborhood's value moves to the median of its sales only with 3+ sales and a move of 15% or less. Bigger moves wait for a decision.",
        "- Sources: Tal's MLS export (through 7/24/2026), Redfin sold data weekly, [LA County fire-damage data](https://data.lacounty.gov/datasets/parcels-2025-fires-debris-removal-public-view)."]
print("\n".join(out))
