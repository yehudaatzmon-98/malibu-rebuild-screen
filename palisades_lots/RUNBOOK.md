# Palisades lots: weekly comps refresh

Keeps the lot model's sale prices current with new closed sales in 90272, then updates the
workbook and the data room. Everything lives in this folder; nothing outside it is touched.

## Files
- `data/lots.csv`, `data/order.txt`, `data/short.txt`: the lot universe, row order, the 6 shortlisted lots.
- `data/nbhd_base.csv`: sale $/sf per neighborhood. `judgment_psf` = Tal/Yehuda's value; `applied_psf` = what the
  model uses; `override_psf` = a manual value that always wins (only Tal/Yehuda set it).
- `data/comps_log.csv`: every sale seen, with neighborhood, fire damage and whether it qualifies.
- `data/reference_points.csv`: coordinates used to match a sale to a neighborhood.
- `data/asking_newbuilds.csv`: new builds for sale (asking prices only, never used as comps).
- `data/damage.csv`: cached LA County fire-damage lookups.
- `update_comps.py`, `build_workbook.py`, `summary.py`, `comps_tab.py`, `redfin_sold.js`.
- `Palisades_Lot_Screen.xlsx`: the current workbook. `reports/`: one report per run.

## Rules (do not change without Yehuda's OK)
- A sale qualifies: house in 90272, closed in the last 24 months, 2,000+ sf, built 2010+, matched to a
  neighborhood, not a burned house sold as a lot (county damage "Destroyed" and built before 2025).
- A neighborhood moves to the median of its qualifying sales only with 3+ sales and a move of 15% or less.
  Anything else is flagged, never applied. Never write override_psf yourself.
- Report only what you read on a page or in the data. Asking prices are labeled as asking.

## Weekly steps
1. `cd palisades_lots`. Save `python3 summary.py > /tmp/before.json` (numbers before this run).
2. Redfin: open https://www.redfin.com/zipcode/90272 in the built-in browser and run `redfin_sold.js` with the
   javascript tool. Save the returned text exactly to `data/incoming/redfin_<YYYY-MM-DD>.txt`.
3. `python3 update_comps.py --new data/incoming/redfin_<date>.txt --asof <date>`.
4. If the report lists "Damage lookups still needed": in the browser, query
   `https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/Parcels_Debris_Removal_Public/FeatureServer/0/query`
   with `where=SITUSADDRESS IN ('<ADDR>',...)`, `outFields=SITUSADDRESS,DAMAGE`, `f=json`. Save
   `{"<ADDR>": "<DAMAGE>"}` to `data/incoming/damage_<date>.json`; any address not returned gets
   "Not in county fire-damage data". Re-run step 3 with `--damage data/incoming/damage_<date>.json`.
5. New builds for sale: if Redfin shows a new 2025+ build listed, pending or price-cut in 90272, update
   `data/asking_newbuilds.csv` (asking prices only). When one closes, it enters through step 3 instead.
6. `python3 build_workbook.py`, then recalculate with LibreOffice (the xlsx skill's `scripts/recalc.py`);
   it must report 0 errors. Then `python3 summary.py > /tmp/after.json` and compare with before.json.
7. Data room (Claude Docs, doc id 5ffcb13e-c541-499f-8117-b00be860f143):
   - Comps tracker tab: replace its whole body with `python3 comps_tab.py <date>` output.
   - If any shortlisted lot's numbers changed: update that lot's tab (lead sentence, max offer line,
     "Cost and profit, medium case" table, "Three scenarios" table), the overview's Lot shortlist table
     and the Portfolio paragraph and table (land, equity, worst/medium/best profit and multiples).
     Read each table before editing; people edit this doc, so never overwrite their words.
   - Lot tab body ids: 711 Chapala 75b580dd-ee3f, 611 Ocampo 930a7cbf-d54f, 16150 Northfield 41021d55-c3e3,
     14410 Villa Woods d3567a36-c05f, 909 Rivas Canyon 1c4e93c0-85b9, 545 N Las Casas ad7e0c81-2509,
     overview 2f38ece2-7438, Comps tracker 2f757e4f-0065.
8. Commit `data/`, `reports/` and the workbook to main with message "Comps refresh <date>" and push.
9. Tell Yehuda (SendUserMessage): new qualifying sales (address, price, $/sf, neighborhood), any neighborhood
   value applied or flagged, and how each shortlisted lot's medium profit and max offer moved. Send the
   workbook with SendUserFile only if numbers changed. If nothing new: one line saying so.
