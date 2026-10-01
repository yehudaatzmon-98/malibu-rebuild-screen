"""Update the Palisades comps log and the neighborhood sale $/sf used by the lot model.

Usage:
  python update_comps.py --new data/incoming/redfin_YYYY-MM-DD.txt [--damage data/incoming/damage_YYYY-MM-DD.json] [--asof YYYY-MM-DD]

--new     pipe-delimited rows from redfin_sold.js:
          sold_date|address|price|sqft|year_built|lot_sf|lat|lon|status|mls|url
--damage  JSON {"1234 STREET NAME": "Destroyed (>50%)", ...} from the LA County debris dataset
          (see RUNBOOK.md). Cached in data/damage.csv.

Rules (also in RUNBOOK.md):
  A sale QUALIFIES as a comp when it is a single-family house in 90272, closed within the last
  24 months, 2,000+ sf, built 2010 or later, assigned to a neighborhood, and not a burned house
  sold as a lot (county damage "Destroyed" and built before 2025).
  Neighborhood = majority code of the 5 nearest reference points within 900 m.
  RULE $/sf for a neighborhood = median $/sf of its qualifying comps, rounded to $10.
  The rule is APPLIED only when it has 3+ comps AND moves the value by 15% or less.
  Otherwise the current value stays and the report flags it for review. A number in
  override_psf always wins.
"""
import argparse, csv, json, math, os, statistics
from collections import Counter
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
LOG = os.path.join(D, "comps_log.csv")
BASE = os.path.join(D, "nbhd_base.csv")
REF = os.path.join(D, "reference_points.csv")
DMG = os.path.join(D, "damage.csv")
FIELDS = ["sold_date", "address", "price", "sqft", "psf", "year_built", "lot_sf", "lat", "lon", "source", "mls", "url",
          "damage", "nbhd", "nearest_ref_m", "qualifies", "reason", "added_on"]
MIN_SF, MIN_YEAR, WINDOW_DAYS, MIN_N, MAX_MOVE = 2000, 2010, 730, 3, 0.15


def norm(a):
    return " ".join(a.upper().replace(",", " ").replace("'", " ").split())


def read_csv(p):
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p, rows, fields):
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def assign(lat, lon, refs, k=5, maxm=900):
    if lat in (None, "") or lon in (None, ""):
        return "", ""
    lat, lon = float(lat), float(lon)
    ds = []
    for r in refs:
        dy = (float(r["lat"]) - lat) * 111000
        dx = (float(r["lon"]) - lon) * 111000 * math.cos(math.radians(34.05))
        ds.append((math.hypot(dx, dy), r["code"]))
    ds.sort()
    if ds[0][0] <= 50:  # sits on a reference point (a labeled comp or a lot): take its code
        return ds[0][1], round(ds[0][0])
    near = [c for d_, c in ds[:k] if d_ <= maxm]
    if not near:
        return "", round(ds[0][0])
    top = Counter(near).most_common()
    best = [c for c, n in top if n == top[0][1]]
    code = next(c for c in near if c in best)  # tie -> nearest
    return code, round(ds[0][0])


def qualify(r, asof):
    try:
        sd = datetime.strptime(r["sold_date"], "%Y-%m-%d").date()
    except Exception:
        return "N", "no sold date"
    if (asof - sd).days > WINDOW_DAYS:
        return "N", "older than 24 months"
    if not r["sqft"] or float(r["sqft"]) < MIN_SF:
        return "N", f"under {MIN_SF:,} sf"
    if not r["year_built"] or int(float(r["year_built"])) < MIN_YEAR:
        return "N", f"built before {MIN_YEAR}"
    if r.get("damage", "").startswith("Destroyed") and int(float(r["year_built"])) < 2025:
        return "N", "burned house sold as a lot"
    if not r["nbhd"]:
        return "N", "no neighborhood match (review)"
    return "Y", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new")
    ap.add_argument("--damage")
    ap.add_argument("--asof", default=date.today().isoformat())
    a = ap.parse_args()
    asof = datetime.strptime(a.asof, "%Y-%m-%d").date()

    refs = read_csv(REF)
    log = read_csv(LOG)
    dmg = {r["address"]: r["damage"] for r in read_csv(DMG)}
    if a.damage:
        dmg.update({norm(k): v for k, v in json.load(open(a.damage)).items()})
        write_csv(DMG, [{"address": k, "damage": v} for k, v in sorted(dmg.items())], ["address", "damage"])

    seen = {(norm(r["address"]), r["sold_date"]) for r in log}
    added = []
    if a.new:
        for line in open(a.new):
            p = line.strip().split("|")
            if len(p) < 11 or not p[0]:
                continue
            sd, addr, price, sf, yb, lot, lat, lon, status, mls, url = p[:11]
            key = (norm(addr), sd)
            if key in seen or not price:
                continue
            row = dict(sold_date=sd, address=addr, price=price, sqft=sf,
                       psf=str(round(float(price) / float(sf))) if sf else "", year_built=yb, lot_sf=lot,
                       lat=lat, lon=lon, source=status if "Tal" in status else "Redfin (" + (status or "sold") + ")", mls=mls,
                       url=("https://www.redfin.com" + url) if url.startswith("/") else url, added_on=a.asof)
            log.append(row)
            seen.add(key)
            added.append(row)

    for r in log:
        r["damage"] = dmg.get(norm(r["address"]), r.get("damage", ""))
        r["nbhd"], r["nearest_ref_m"] = assign(r["lat"], r["lon"], refs)
        r["qualifies"], r["reason"] = qualify(r, asof)
    log.sort(key=lambda r: r["sold_date"], reverse=True)
    write_csv(LOG, log, FIELDS)

    # needs a damage check: post-fire sales that would otherwise qualify but have no damage record looked up
    need_dmg = sorted({norm(r["address"]) for r in log if r["sold_date"] >= "2025-01-07" and r["qualifies"] == "Y"
                       and norm(r["address"]) not in dmg})

    base = read_csv(BASE)
    changes, flags = [], []
    for b in base:
        q = [float(r["psf"]) for r in log if r["qualifies"] == "Y" and r["nbhd"] == b["code"] and r["psf"]]
        old = float(b["applied_psf"])
        b["rule_n"] = str(len(q))
        b["rule_psf"] = str(int(round(statistics.median(q), -1))) if q else ""
        if b["override_psf"]:
            new, status = float(b["override_psf"]), "override"
        elif len(q) >= MIN_N and abs(float(b["rule_psf"]) / float(b["judgment_psf"]) - 1) <= MAX_MOVE:
            new, status = float(b["rule_psf"]), f"rule ({len(q)} comps)"
        else:
            new, status = float(b["judgment_psf"]), "judgment"
            if len(q) >= MIN_N:
                flags.append(f"{b['code']}: {len(q)} comps give ${int(float(b['rule_psf'])):,}/sf vs ${int(float(b['judgment_psf'])):,} judgment (more than 15% apart, not applied; review and set override_psf if right)")
        if new != old:
            changes.append(f"{b['code']}: ${int(old):,} -> ${int(new):,}/sf ({status})")
            b["updated"] = a.asof
        b["applied_psf"], b["status"] = str(int(new)), status
    write_csv(BASE, base, ["code", "judgment_psf", "applied_psf", "override_psf", "rule_psf", "rule_n", "status", "note", "updated"])

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    rep = [f"# Comps update {a.asof}", ""]
    rep += ["## New sales added", ""] + ([f"- {r['sold_date']} {r['address']}: ${int(float(r['price'])):,}, {r['sqft']} sf, built {r['year_built']}, "
                                         f"{'$' + r['psf'] + '/sf' if r['psf'] else ''} -> {next((x['nbhd'] or 'no nbhd') for x in log if x is r)}, "
                                         f"{'QUALIFIES' if r['qualifies'] == 'Y' else 'not a comp: ' + r['reason']}" for r in added] or ["- none"])
    rep += ["", "## Neighborhood $/sf changes applied", ""] + ([f"- {c}" for c in changes] or ["- none"])
    rep += ["", "## Flagged for review", ""] + ([f"- {f}" for f in flags] or ["- none"])
    rep += ["", "## Damage lookups still needed", ""] + ([f"- {x}" for x in need_dmg] or ["- none"])
    rep += ["", "## Current neighborhood values", "", "| Code | Applied $/sf | Status | Qualifying comps | Rule median |", "| --- | --- | --- | --- | --- |"]
    rep += [f"| {b['code']} | ${int(float(b['applied_psf'])):,} | {b['status']} | {b['rule_n']} | {('$' + format(int(float(b['rule_psf'])), ',')) if b['rule_psf'] else '-'} |" for b in base]
    out = os.path.join(HERE, "reports", f"comps_{a.asof}.md")
    open(out, "w").write("\n".join(rep) + "\n")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
