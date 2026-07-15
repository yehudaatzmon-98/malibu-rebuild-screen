# Malibu Rebuild Screen

Takes a Redfin export of new listings and returns which lots are worth an afternoon.

## What it does

For every address in the file it queries the **LA County Assessor** (live, public, no key) and returns what actually burned — prior square footage, year built, units, use code, real coordinates — then applies **LCP & Zoning Code Interpretation No. 24** (adopted 15 Oct 2025) and stamps each lot ELIGIBLE / EXCLUDED / UNSCOREABLE, with the rule that produced the verdict.

It is **not a valuation.** It answers one question: is this lot worth your time?

## Why the county lookup matters

A Redfin export has no prior square footage. Burned lots show dashes across beds/baths/sqft — that's how you know it's a lot. But prior sqft is the input the entire rebuild rule rests on, and it lives in the assessor record.

The county call is what makes this work without a manual lookup per lot. It also catches things a human had to read the rule to spot:

- **Multifamily prior use** → No Net Loss (Issue No. 8 / SB 166). A 3-unit building replaced by a house requires 2 ADUs, which eat envelope. Auto-excluded.
- **Assessor vs listing conflicts** → one lot in the test set had a county record of 1,671 sf against a listing claim of 2,452 sf. A 47% gap. Auto-flagged; a survey is required at Planning Verification precisely because of this (Issue No. 12).
- **No prior structure on record** → no envelope to compute. Auto-marked unscoreable rather than guessed.

## The finding this tool exists to surface

**Interpretation No. 24, Issue No. 1: a replacement may not exceed 110% of the previous structure's bulk (volume), square footage, OR height.** Three ceilings, all binding at once.

```
buildable = min( prior_sf × 1.10 , (prior_sf × prior_ceiling × 1.10) ÷ proposed_ceiling )
```

The volume ceiling binds whenever you build taller ceilings than what burned. A 1963 beach house has ~8.5ft ceilings; a 2026 luxury build wants 10ft. At that ratio you get **less square footage than burned**, not the +10% the thesis assumes.

On every lot tested, volume bound — not square footage.

| Lot | Prior sf | Built | Buildable @10ft | vs prior |
|---|---|---|---|---|
| 20610 PCH | 1,760 | 1963 | 1,646 | −7% |
| 21006 PCH | 989 | 1923 | 870 | −12% |
| 20838 PCH | 1,970 | 2017 | 2,059 | +5% |
| 20802 PCH | 2,261 | 1983 | 2,114 | −6% |
| 20048 PCH | 1,671 | 1939 | 1,470 | −12% |

## What's fixed and what's yours

**Fixed (the rule, cited):** the 110% factor, three simultaneous ceilings, basements and subterranean garages counting toward the same 110%, No Net Loss on multifamily.

**Yours:** the ceiling height you'd build, and any basement. Both are surfaced as inputs because they're decisions, not facts — and ceiling height is the single biggest lever in the whole rule.

**Estimated:** prior ceiling height, derived from year built. No record source exists — it lives in the original plans.

## Running it

```
pip install -r requirements.txt
streamlit run screen.py
```

Deploy: push to GitHub, connect at share.streamlit.io. The county endpoint is public and needs no key, so it works on the free tier.

## Data source

`https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0`

LA County Assessor parcel layer. ~2.4M parcels, refreshed weekly, public, no auth. Fields used: `SQFTmain1..5`, `YearBuilt1..5`, `Units1..5`, `UseCode`, `UseDescription`, `DesignType1..5`, `CENTER_LAT`, `CENTER_LON`.

The address join is clean, not fuzzy: `SitusHouseNo` is a separate field in the county schema, so the match is an exact house number plus a street LIKE. No string-similarity guessing.

## One caveat

The county endpoint was verified live and its schema confirmed, but the sandbox this was built in blocks that host, so the actual query path is untested end to end. It will run on Streamlit Cloud, which has open egress. Verify on first run: use the "Check one address" tab with `20610 Pacific Coast Hwy` — the county should return 1,760 sf, built 1963, AIN 4450-005-060.
