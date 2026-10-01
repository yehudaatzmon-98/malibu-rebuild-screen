"""Daily refresh of the lot list from Redfin's active land listings in 90272.

Usage:
  python update_lots.py --land data/incoming/land_YYYY-MM-DD.txt [--permits data/incoming/permits_YYYY-MM-DD.json] [--asof YYYY-MM-DD]

--land     pipe rows from redfin_land.js: address|price|lot_sf|lat|lon|redfin_property_id
--permits  JSON for NEW lots only: {"<address as in the land file>": {"approved_sf": 5094 or null, "note": "..."}}
           (LADBS open data, see RUNBOOK.md). Without it, new lots get approved = blank and the report lists
           them under "Permit check needed".

What it does:
  - price changes on lots we track -> new asking price (logged in data/lots_changes.csv)
  - lots no longer listed -> moved to data/lots_offmarket.csv (logged)
  - new listings -> added with neighborhood (nearest reference points), lot size from Redfin, prior home
    size from LA County parcel data. Skipped (and reported): address number 0, asking under $500K,
    lots over 100,000 sf. A new lot with no county record of a prior home gets prior_sf 0 and the flag
    "prior home size unknown".
"""
import argparse, csv, json, os, re, subprocess
from datetime import date
from update_comps import assign, read_csv

HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
LOTS, ORDER = os.path.join(D, "lots.csv"), os.path.join(D, "order.txt")
OFF, CHG = os.path.join(D, "lots_offmarket.csv"), os.path.join(D, "lots_changes.csv")
HDR = ["address", "submarket", "ask", "prior_sf", "plan_sf", "lotsf", "flags", "approved"]
SUFFIX = {"st", "dr", "ave", "av", "pl", "ln", "blvd", "rd", "way", "ct", "ter", "pkwy", "cir", "e", "w", "n", "s", "unit", "a", "b"}
COUNTY = "https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query"


def key(addr):
    t = re.sub(r"[^a-z0-9 ]", " ", addr.lower()).split()
    if not t: return ""
    num, rest = t[0], [w for w in t[1:] if w not in SUFFIX]
    return num + "".join(rest)


def read_lots():
    rows = []
    with open(LOTS, newline="") as f:
        for r in csv.reader(f):
            if r and not r[0].startswith("#"):
                rows.append(dict(zip(HDR, r + [""] * (len(HDR) - len(r)))))
    return rows


def write_lots(rows):
    with open(LOTS, "w", newline="") as f:
        w = csv.writer(f); f.write("# " + ",".join(HDR) + "\n")
        for r in rows: w.writerow([r[h] for h in HDR])


def append(path, fields, rows):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new: w.writeheader()
        w.writerows(rows)


def county_prior_sf(addr):
    t = addr.upper().split()
    num = t[0]; words = [w for w in t[1:] if w.lower() not in SUFFIX]
    if not words: return None
    street = words[0] if len(words[0]) > 3 or len(words) == 1 else " ".join(words[:2])
    where = f"SitusHouseNo='{num}' AND SitusZIP LIKE '90272%' AND SitusStreet LIKE '%{street}%'"
    try:
        out = subprocess.run(["curl", "-s", "-m", "30", "--data-urlencode", f"where={where}", "--data",
                              "outFields=SQFTmain1,AIN,UseDescription&returnGeometry=false&f=json", COUNTY], capture_output=True, text=True).stdout
        f = json.loads(out).get("features", [])
        if len(f) > 1 or (f and not str(f[0]["attributes"].get("UseDescription") or "").startswith("Single")):
            return "multi"
        if f: return f[0]["attributes"].get("SQFTmain1") or 0
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--land", required=True); ap.add_argument("--permits"); ap.add_argument("--asof", default=date.today().isoformat()); ap.add_argument("--dry", action="store_true", help="report only, write nothing (use first to get the list of new lots that need a permit check)")
    a = ap.parse_args()
    refs = read_csv(os.path.join(D, "reference_points.csv"))
    permits = json.load(open(a.permits)) if a.permits else {}
    lots = read_lots(); order = [l.strip() for l in open(ORDER) if l.strip()]
    land = []
    for line in open(a.land):
        p = line.strip().split("|")
        if len(p) >= 6 and p[1]:
            land.append(dict(address=p[0], price=int(float(p[1])), lot=p[2], lat=p[3], lon=p[4], pid=p[5]))
    lk = {key(x["address"]): x for x in land}
    changes, gone, added, skipped, need_permit = [], [], [], [], []
    keep = []
    for r in lots:
        x = lk.pop(key(r["address"]), None)
        if not x:
            gone.append(r); continue
        if int(float(r["ask"])) != x["price"]:
            changes.append(dict(date=a.asof, address=r["address"], change="price", old=r["ask"], new=x["price"]))
            r["ask"] = str(x["price"])
        keep.append(r)
    for x in lk.values():
        num = x["address"].split()[0]
        if num == "0" or x["price"] < 500000 or (x["lot"] and float(x["lot"]) > 100000) or not x["lot"]:
            skipped.append(f"{x['address']} (${x['price']:,}, lot {x['lot'] or '?'} sf): not added (raw land, under $500K, or no lot size)")
            continue
        code, dist = assign(x["lat"], x["lon"], refs)
        if not code:
            skipped.append(f"{x['address']}: no neighborhood match within 900 m; add by hand"); continue
        prior = county_prior_sf(x["address"])
        if prior == "multi":
            skipped.append(f"{x['address']}: county shows several units or a non-single-family use; not added"); continue
        flags = [f"new listing {a.asof}"]
        if prior is None: flags.append("prior home size unknown"); prior = 0
        pm = permits.get(x["address"])
        if pm is None: need_permit.append(x["address"])
        row = dict(address=x["address"], submarket=code, ask=str(x["price"]), prior_sf=str(int(prior)),
                   plan_sf=str(int(pm["approved_sf"])) if pm and pm.get("approved_sf") else "", lotsf=str(int(float(x["lot"]))),
                   flags="; ".join(flags + ([pm["note"]] if pm and pm.get("note") else [])), approved="Y" if pm and pm.get("approved_sf") else "")
        keep.append(row); added.append(row)
        changes.append(dict(date=a.asof, address=x["address"], change="new listing", old="", new=x["price"]))
    for r in gone:
        changes.append(dict(date=a.asof, address=r["address"], change="left active listings (pending, sold or withdrawn)", old=r["ask"], new=""))
    rep = {"price_changes": [c for c in changes if c["change"] == "price"], "new": [r["address"] for r in added],
           "off_market": [r["address"] for r in gone], "skipped": skipped, "permit_check_needed": need_permit}
    if a.dry:
        print(json.dumps(rep, indent=1)); return
    if gone: append(OFF, ["date"] + HDR, [dict(r, date=a.asof) for r in gone])
    if changes: append(CHG, ["date", "address", "change", "old", "new"], changes)
    write_lots(keep)
    live = {r["address"] for r in keep}
    order = [o for o in order if o in live] + [r["address"] for r in added if r["address"] not in order]
    open(ORDER, "w").write("\n".join(order))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
