# Palisades lots: daily refresh

Every morning: re-price every 90272 lot listing (price cuts, new listings, lots that went pending),
add new closed home sales to the comps, rerun the model, update the data room, and tell Yehuda what
changed. Everything lives in this folder; nothing outside it is touched.

## Files
- `data/lots.csv`, `data/order.txt`: the lot universe and row order. `data/short.txt`: the 6 shortlisted lots.
- `data/excluded.csv`: lots Tal or Yehuda removed (e.g. 1785 Alta Mura, Tal 10/1). Never add them back, even if they relist.
- `data/lot_features.txt`: per lot, whether the MLS view field names an ocean view and whether it is gated
  (`address|ocean_view|gated|mls_view`). Ocean view = the MLS VIEW_DESCRIPTION contains Ocean, Coastline, Catalina,
  White Water or Bay; it adds the Assumptions tab's ocean-view premium ($100/sf, Tal 10/1). Gated premium is $0 until Tal sets it.
- `data/lots_changes.csv`: every price change, new listing and lot that left the market. `data/lots_offmarket.csv`.
- `data/nbhd_base.csv`: sale $/sf per neighborhood. `judgment_psf` = Tal/Yehuda's value; `applied_psf` = what the
  model uses; `override_psf` = a manual value that always wins (only Tal/Yehuda set it).
- `data/comps_log.csv`: every home sale seen, with neighborhood, fire damage and whether it qualifies.
- `data/asking_newbuilds.csv`: new builds for sale (asking prices only, never used as comps).
- `data/reference_points.csv`, `data/damage.csv`: neighborhood matching and cached fire-damage lookups.
- Scripts: `redfin_land.js`, `redfin_sold.js` (run in the browser), `update_lots.py`, `update_comps.py`,
  `build_workbook.py`, `snapshot.py`, `summary.py`, `comps_tab.py`, `lots_tab.py`, `shortlist_md.py`, `model_tab.py`.
- `data/plan10.txt`: the lots in the 10-lot plan. Only Tal or Yehuda change it.
- `Palisades_Lot_Screen.xlsx`: the current workbook. `reports/`: one comps report per run.

## Rules (do not change without Yehuda's OK)
- Comps: a sale qualifies if it is a house in 90272, closed in the last 24 months, 2,000+ sf, built 2010+,
  matched to a neighborhood, and not a burned house sold as a lot (county damage "Destroyed", built before 2025).
- New builds (built 2025+, including homes sold during construction once they close) are the best comps:
  with 2+ in a neighborhood their median sets the value; otherwise 3+ sales of 2010+ homes do.
- A neighborhood value changes only if that rule moves it 15% or less. Bigger moves are flagged, never applied.
  Never write override_psf yourself.
- Lots: new listings under $500K, over 100,000 sf, numbered 0, or on multi-unit parcels are skipped and reported.
  A lot with no prior home on record is added but flagged: its size is a zoning guess, so never call it a deal
  without saying so.
- Report only what you read on a page or in the data. Asking prices are always labeled as asking.

## Daily steps
1. `cd palisades_lots`. Snapshot before: `python3 snapshot.py > /tmp/before.json` and `python3 summary.py > /tmp/sum_before.json`.
2. Lots. In the built-in browser open https://www.redfin.com/zipcode/90272, run `redfin_land.js` with the javascript
   tool, and save the text exactly to `data/incoming/land_<date>.txt`.
   - `python3 update_lots.py --land data/incoming/land_<date>.txt --asof <date> --dry` lists new lots.
   - For each new lot, check LADBS open data in the browser
     (`https://data.lacity.org/resource/gwh9-jnip.json?apn=<AIN>` — get the AIN from the LA County parcel layer,
     or `$where=primary_address like '<NUM> <STREET>%'`). A Bldg-New single-family application with status
     "PC Info Complete" or "Plan Check Approved" = approved plans; open its LADBS Permit Report to read the size.
     Save `{"<address>": {"approved_sf": <sf or null>, "note": "<what you found, with permit number>"}}` to
     `data/incoming/permits_<date>.json`.
   - Run `update_lots.py` again without `--dry`, with `--permits data/incoming/permits_<date>.json`.
   - For each new lot, open its Redfin page and read the MLS "View" field (VIEW_DESCRIPTION) and whether the
     listing says gated / guard-gated; append a line to `data/lot_features.txt`. Report only what the page says.
   - For any shortlisted or watch-list lot that left the listings, open its Redfin page and record what it says
     (pending, contingent, sold, withdrawn) in `data/lots_changes.csv`.
3. Comps. Run `redfin_sold.js` (set DAYS = 10) and save to `data/incoming/redfin_<date>.txt`, then
   `python3 update_comps.py --new data/incoming/redfin_<date>.txt --asof <date>`.
   If the report lists "Damage lookups still needed": query
   `https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/Parcels_Debris_Removal_Public/FeatureServer/0/query`
   in the browser (`where=SITUSADDRESS IN ('<ADDR>',...)`, `outFields=SITUSADDRESS,DAMAGE`, `f=json`), save
   `{"<ADDR>": "<DAMAGE>"}` (missing = "Not in county fire-damage data") to `data/incoming/damage_<date>.json`,
   and re-run with `--damage`.
4. New builds for sale: if a new 2025+ build in 90272 listed, cut its price or went pending, update
   `data/asking_newbuilds.csv` (asking prices only).
5. `python3 build_workbook.py`, then recalculate with LibreOffice (the xlsx skill's `scripts/recalc.py`); it must
   report 0 errors. Then `python3 snapshot.py > /tmp/after.json`, `python3 summary.py > /tmp/sum_after.json`, and
   `python3 snapshot.py --diff /tmp/before.json /tmp/after.json` for the report.
6. Data room (Claude Docs, doc id 5ffcb13e-c541-499f-8117-b00be860f143). Read before every edit; people edit this
   doc, so never overwrite their words.
   - Every run: replace the All lots tab's whole body with `python3 lots_tab.py <date>`: one batch that creates a new
     prose node (parent file a78c458d-13dc, markdown from lots_tab.py) and updates file a78c458d-13dc's content to it. This tab is the live lot screen Tal and investors use instead of the spreadsheet, so it must always match the model.
   - Every run, the same way (new node, then point the file at it): the "10-lot plan (updated daily)" tab (file
     d6b1d72a-9c55) from `python3 model_tab.py plan <date>`, and the "Model inputs & math (updated daily)" tab
     (file e75fea13-dd74) from `python3 model_tab.py inputs <date>`. These two tabs replace the spreadsheet: every
     input, every cost line and the deal split come only from these scripts, never hand-typed. The inputs tab is
     large; if one create call is too big, create the node with everything up to "## Full cost build-up", point the
     file at it, then insert the rest at the end of that node. If `model_tab.py plan` reports a plan lot no longer
     listed, or a plan lot drops below 15%, say so in the report. Never edit data/plan10.txt yourself.
   - If comps changed: replace the Comps tracker tab's whole body with `python3 comps_tab.py <date>`.
   - If a shortlisted lot's numbers changed (compare sum_before/sum_after): run `python3 shortlist_md.py` and update
     that lot's tab from its output (lead sentence, max offer line, house line, "Cost and profit, medium case" table,
     "Three scenarios" table, build-cost sensitivity line); run `python3 shortlist_md.py --overview` for the overview's
     Lot shortlist table and Portfolio paragraph and table.
   - If any 10-lot plan lot changed price or status, or the plan's "we get" numbers moved, say so in the report.
   - If a watch-list lot changed status or price, update its row in the overview's Watch list table.
   - Tab body ids: overview 2f38ece2-7438, All lots (file a78c458d-13dc; body changes on every swap), 10-lot plan (file d6b1d72a-9c55), Model inputs & math (file e75fea13-dd74), Comps tracker 2f757e4f-0065, 711 Chapala 75b580dd-ee3f,
     611 Ocampo 930a7cbf-d54f, 16150 Northfield 41021d55-c3e3, 14410 Villa Woods d3567a36-c05f,
     909 Rivas Canyon 1c4e93c0-85b9, 545 N Las Casas ad7e0c81-2509, Terms 2a119a58-686c.
7. Commit `data/`, `reports/` and the workbook to main ("Daily refresh <date>") and push.
8. Tell Yehuda (SendUserMessage), changes only: the diff report (price cuts with the new margin and max offer,
   lots newly clearing 15%, new listings, lots that went pending/sold), new qualifying home sales (address, price,
   $/sf, neighborhood, new build or not), neighborhood values applied or flagged, and any shortlist number that
   moved, and say the data room is updated. Do NOT send the workbook: the data room is the single place Tal and
   investors look, so nobody should have to pass spreadsheet versions around. If nothing changed: one line.
