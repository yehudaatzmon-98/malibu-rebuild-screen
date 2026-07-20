# Palisades · Malibu Lot Analyzer

A two-stage development-underwriting funnel:

1. **Screener** (`screen.py`) — one lot at a time. Eligibility, buildable envelope,
   and the full rule engine: jurisdiction routing (Malibu Interp. No. 24 vs City of
   LA EO1/EO8), the beachfront fork, TDSF, SPR suspension, the access cliff,
   entitlement status, height conformity, the census/PRA move. Answers "can I build
   it, and what."

2. **Analyzer** (`app.py`) — a whole Redfin CSV at once. Runs each lot through the
   screener's eligibility and envelope, then adds the money case: jurisdiction-
   segmented comps, cost stack, return on cost, ranking. Answers "will it make
   money," across the market.

## The two rules that keep it honest

- **Comps are jurisdiction-segmented and never blended.** Malibu and Palisades are
  different markets under different rulebooks. The loaded comp set is Palisades-only
  (263 sold sales, 2023–2026), so Malibu lots return NO BASIS rather than a borrowed
  number. Supply Malibu comps to price that side.
- **Range, not verdict.** The comps don't reconcile tightly. Each lot shows a range
  and what you'd have to believe — a sort order and a decision scaffold, not a green
  light.

## Files
- `screen.py` — single-lot screener UI
- `app.py` — batch analyzer UI
- `engine.py` — money engine (comp matching, cost stack, return), UI-independent
- `county.py` — LA County Assessor enrichment + the rule engine
- `jurisdiction.py` — Malibu vs City of LA routing
- `comps_database.csv` — 263 Palisades sold sales
- `sample_redfin_export.csv` — demo input

## Run
```bash
pip install -r requirements.txt
streamlit run app.py      # the batch analyzer
streamlit run screen.py   # the single-lot screener
```

## The yardstick (defaults)
Construction $1,000/sqft fully loaded · contingency 8% · carry 3%/yr · selling 5% ·
appreciation 3%/yr · new-build premium 10%. Every one is a slider; move it and the
whole list re-scores together on the same version stamp.
