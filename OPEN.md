# OPEN — PCR / Palisades

Single source of truth. Lives in the repo, changes by commit. **Replaces the handover-document
habit** — handovers duplicated, contradicted each other, and carried findings forward with more
confidence than they earned. If a claim is not here or in the code, it is not current.

Last updated: **18 September 2026**

---

## 0 · Where this stands, in one paragraph

The builder (Tal Karasso, steel construction) has offered **$550/sf for a share of profit**, down
from a verbal **$800/sf cap including Chapter 7A**. Under Tal Topel's exit assumption of **$1,800/sf
at sale**, nine of twenty screened lots clear 12%+ at full ask on $800, and 45–52% on $550. **Three
lots are recommended for pursuit: 826 Jacon Way, 16150 Northfield St, 1425 Monte Grande Pl.** The
largest unresolved variable in the entire model is the exit price, where the model's existing-home
comps ($1,150–$1,250) and Tal's framework ($1,800–$2,060) differ by roughly 60%.

---

## 1 · The three to pursue

| # | Lot | Ask | Envelope | RTI | ROC @$800 | ROC @$550 | Action |
|---|---|---|---|---|---|---|---|
| 1 | **826 Jacon Way** | $1,350,000 | 5,141 sf | **YES** | 15% | 50% | Offer at ask |
| 2 | **16150 Northfield St** | $1,395,000 | 5,238 sf | **YES** | 14% | 49% | Offer $1.30M |
| 3 | **1425 Monte Grande Pl** | $1,495,000 | 5,900 sf | no | 16% | 52% | Offer at ask |

**826 Jacon** is first: permits approved and ready to issue (house, grading, retaining wall), LADBS
shows "PC Info Complete", geotech done and accepted, large flat building pad, no rear neighbour, ADU
in the approved set. Seller bought 8/2018 at $2,167,000 and is roughly $800K underwater.
Categorical Exclusion, single permit jurisdiction. Landslide zone YES, so geotech is a permit gate
and one exists.

**16150 Northfield** — RTI for 5,238 sf (Option B: 4,238 main + 1,000 ADU). Seller bought 27 Jan
2025, twenty days after the fire, at $1,165,000, and has already cut from $1.45M. Hillside YES,
landslide NO, CATEX coastal. **Correction: killed on 8 Sep on a 2,500 sf envelope. That was wrong —
the envelope was wrong, not the lot.**

**1425 Monte Grande Pl Lot 3** — best ROC on the board. Not RTI, so 35 months rather than 24. A 2023
lease listing claimed 5,800 sf of plans; unverified. Highlands, canyon view.

**Deliberately not pursued: 16740 Monte Hermoso** (15% at ask). Four burned lots are for sale on
that one block — 16726 $1.825M, 16740 $1.65M, 16748 $1.675M, 16756 $1.895M. Whoever builds exits
into three identical competing products finishing at the same time.

---

## 2 · THE decisive open question: what does a new build sell for?

Everything turns on this. Nothing else is close.

| Source | Exit $/sf | Basis |
|---|---|---|
| Model's existing-home comps | $1,150–$1,250 | 1950s–1990s houses, recorded sales |
| Observed new builds, Enchanted Way | **$2,052 and $2,129** | two sales, same tract |
| Tal Topel's framework | $1,500–$1,600 today → **$1,934–$2,062** at 2029 | 5%/yr + 10% new-build premium |
| Developer (Monte Hermoso call) | $1,700 "worst case", $2,000 upside | assertion |
| `market.py` measured premium | +9.4%, CI spans zero, defaults to 0 | sample too small to detect |

**The model has a structural defect here, and it is not calibration.** `CompMarket.match()` never
references `year_built` — confirmed by inspection. It prices a 2030 new build off a median of 30 to
50 year old houses. Within a mile of Monte Hermoso there are 131 recorded sales, every one built
1966–1997, and **zero new-construction sales**. The basis is not wrong; what it is applied to is.

**Required fix, one session:** build a new-construction comp set from Tal's 1,184-sale file
(post-fire deliveries first, then 2018–2024 new builds), measure the premium over existing homes by
tier, and rewrite `CompMarket` to match on product class → tier → size. Then report exit as three
labelled numbers on every lot — existing-home floor, new-build central, Tal's framework as a
labelled bet — never one number.

---

## 3 · The $550 construction offer

Karasso: $550/sf plus a share of profit, against his earlier $800/sf cap including 7A.

**The structure is good for us if the number is real.** He defers $250/sf, about $1.25M on a
5,000 sf house, and is repaid only out of profit. Breakeven profit shares — above which $550 plus a
share costs more than $800 flat — run **60% to 82% depending on the lot** (Monte Grande 60%,
Northfield 62%, Cumbre Verde and 16740 Monte Hermoso 63%, Oreo 73%, 16726 Monte Hermoso 82%). Any
share under 50% and we are clearly ahead.

**Three things must be true before it is a cost rather than a conversation:**

1. Same scope as the $800. A 31% drop from the same firm in 48 hours is either a very large margin
   or a different scope — shell only, excluding site work, retaining, utilities, ADU. Needs to be in
   writing with exclusions listed.
2. Steel at $550 needs explaining. Light-gauge steel in single-family is normally *more* than wood
   unless he panelises in his own facility. If he does, that is a real edge. If not, the number
   needs a source.
3. **The profit share percentage has not been stated.**

**COUNSEL, time-critical.** A GC taking profit share is a co-sponsor, not a vendor. Three-way
waterfall: before or after the LP preferred return? Before or after the sponsor promote? Does he
share losses or only forfeit upside? This belongs in the offering documents. The non-arm's-length
construction disclosure was already mandatory at $800; at $550 with equity it *is* the deal.

---

## 4 · Tal's 9/17 spreadsheet — keep, with four fixes

Useful and worth keeping. Four things in it repeat mistakes this project already made:

1. **Land $/sf = list price ÷ prior house sq ft.** This is the exact artifact behind the withdrawn
   17% burn discount. Prior square footage is not a denominator for land.
2. **Assessor SqftMain is not verified.** 865 Oreo shows 4,896 on the Assessor and **4,202 on its
   two Certificates of Occupancy** in our own `verified_records.csv`.
3. **$1,800/sf flat from Huntington to the Highlands** blends tiers (rule 3).
4. **EO1 only for non-RTI lots** contradicts the compute-both rule. 627 Marquette shows a $149K
   margin at 1,148 sf (EO1) when the ordinance gives 3,147 sf.

**It also omits about $18.9M of cost across the ten lots**, against an aggregate gross margin of
$27.2M. Missing: financing and carry, selling costs, Measure ULA, contingency, soft costs beyond
A&E.

**Two-batch split (his idea, adopted):** RTI lots that can start immediately, versus lots needing
full permits. RTI batch = 865 Oreo, 16150 Northfield, 14736 McKendree (claim unverified), plus
**826 Jacon**, which is not on his sheet.

---

## 5 · Open items, by value

| # | Item | Worth | With |
|---|---|---|---|
| 1 | **New-construction comp set + `CompMarket` product-class fix** | The whole ranking; ~60% exit spread | us, one session |
| 2 | **$550 in writing: scope, exclusions, profit share %** | Every return figure | Karasso |
| 3 | **Approved plan sets** for Jacon and Northfield | Confirms envelope and ADU | listing agents |
| 4 | **Counsel on the three-way waterfall** | Cannot be retrofitted | Tal |
| 5 | **Burned/not-burned flag per parcel** (fire perimeter join) | ~$270/sf exit ambiguity | records |
| 6 | Monte Grande: do the 5,800 sf plans exist, were they submitted | Envelope | listing agent |
| 7 | Akron: C of O for the 2008 4,085 sf build | EO1 vs ordinance, 28% of envelope | LADBS |
| 8 | Akron: why 226 DOM (16550 $1M; nearby Akron lots $2M/$2.1M at 338 DOM) | Street or lot | agent |
| 9 | 627 Marquette: ask HRD Arch (Hamid Dehghan, 310-359-2245) whether slope forces the 25% guaranteed minimum | Envelope | free call |

**Public sources that work.** LADBS Property Activity Report (ladbs.org → Online Services) for
permit status and approved floor area. Palisades permit concierge:
**palisadespermitconcierge@lacity.org**. ZIMAS does *not* hold permits or plans — zoning and hazards
only.

---

## 6 · Withdrawn findings

All shared one signature: **a number quoted without inspecting the rows behind it.**

| Finding | Withdrawn | Why |
|---|---|---|
| 17% burn-zone discount | 8 Sep | Composition — land trades read as cheap houses |
| Size-band trough | 8 Sep | Composition — post-fire elasticity is +0.182; build to the envelope |
| Exit basis $1,542/sf and DiD +13.2% | 8 Sep | **Selection on the outcome variable** — deleting the 43 lowest of 134 post-fire sales and comparing against an uncut pre-fire set |
| "Jacon works at or below $825/sf" | 16 Sep | Computed against the withdrawn exit basis |
| "623 Marquette clears 20%" | 16 Sep | Same |
| "16150 Northfield is dead" | 18 Sep | **Envelope was wrong — 2,500 vs RTI 5,238** |
| "The ADU moves breakeven from $28K to $947K" | 17 Sep | Assumed an ADU foot sells at the main-house rate; real value is $40–105K |
| 14410 Villa Woods +5.8% | 16 Sep | Comp-matcher artifact — the same-street sale 0.03 mi away is $1,263, not the $2,041 Riviera set |

**Land-trade separation is still unsolved.** Neither $/house-ft nor $/lot-ft separates land trades
from standing homes; both distributions are continuous with no break. Only the burned flag (item 5)
resolves it. **No classifier is encoded, by choice.**

---

## 7 · What is settled

- **ULA is permanent** (repeal closed 25 June 2026). Indexed; 2030 tier-1 threshold ≈ $5.96M.
- **Build timelines 30–35 months** (501 Swarthmore 34, 16815 Livorno 35, from LADBS records).
- **Storeys do not add area.** R1 caps floor area. Build up for site coverage.
- **Redfin lot sizes are unreliable on cut parcels** — 2 of 9 off by 2–4x. ZIMAS only.
- **Prior square footage from a sheet, listing or agent has been wrong 5 of 5**, always overstated.
  The Certificate of Occupancy is the only authoritative source.
- **The coastal gate** is Categorical Exclusion or Calvo → pass, ministerial; Single Permit alone →
  flag; Dual Permit → exclude. This is the test, *not* "in the Coastal Zone", which covers most of
  the Palisades. 623 and 627 Marquette pass: CDP DIR-2022-4420-CDP-MEL-HCA issued 25 Oct 2023 with
  the single-permit box checked.
- **Hillside ≠ expensive foundation.** Two independent geotechs — Soil Pacific A-8261-20 on 627 and
  Schick on 623 — both report dense native material about 2 ft down, expansion index 0, conventional
  spread footings at 2,000 psf, no major excavation. Landslide-zone mapping is the real gate.

---

## 8 · Code state

`MARKET_VERSION` must read **m2.0**.

**NOT IN THE REPO — the 16 Sep session's files were never pushed:**

- `slope_bands.py` (new module: measured slope bands from LARIAC contours, feeding
  `bho_rfa(bands_sqft=…)`)
- the `bho.py` variation-zone flag (R1H1, R1V2, R1F return no envelope)
- that session's `OPEN.md` and `verified_records.csv` updates

Fixed 8 Sep and present in the repo: distance-gated comp pool (0.75 / 1.25 / 2 / 3 mi ladder);
`parcel_hillside` now outranks the street-name list; NaN square-footage guard; SFR-only pool with a
known sale date; weighted median rather than weighted mean.

**Known defects, unfixed:**

- `CompMarket` has **no product-class or vintage dimension** (item 1). This is the big one.
- It still **blends price tiers inside 0.75 mi** in the Riviera and the Village. Verified three
  times: Swarthmore (La Cumbre Riviera comps), Villa Woods (basis swung $1,263 → $2,041 on envelope
  size alone), Enchanted (basis falls as the envelope rises).
- `bho.py` does not recognise Palisades R1 variation zones.
- Vestigial burn-recovery slider still in `app.py`.
- Engine default `appreciation_pct` is 0.03 — a forecast sitting inside the base case. Should be a
  labelled slider at 0.

---

## 9 · Measured envelopes (16 Sep, LARIAC contours — DRAFT, not a stamped Slope Analysis Map)

| Lot | Envelope | EO1 | Path |
|---|---|---|---|
| 16550 Akron | 3,518 | 4,494 (Assessor only) | EO8, or EO1 if a C of O confirms |
| 922 Enchanted | 6,505 | 3,210 | EO8 |
| 826 Jacon | 5,141 | 2,589 | EO8 |
| 623 Marquette | 3,169 | 1,863 | EO8 |
| 627 Marquette | 3,147 | 1,584 | EO8 |

No floor-area bonus in the base case; Ordinance 184,802 limited the options. 627 Marquette's own
architect (HRD Arch, plan sheet C1) used **1,947 sf, the BHO guaranteed minimum**, not the 3,399 the
listing claims. See item 9 in section 5.

---

## 10 · Working rules that keep being relearned

1. **Look at the rows before quoting the number.** Every failed finding broke this one.
2. **Verify before ranking.** Unverified figures have moved the wrong way every time.
3. **Comps are jurisdiction- and tier-segmented, never blended.**
4. **Compute both rebuild paths and take the larger.**
5. **Range, not verdict.** Show what you would have to believe.
6. **Separate measurement from bet.** Scarcity, escalation and burn-recovery stay labelled at zero.
7. **State what is unknowable rather than estimating it.** The land-trade split is the live example.
8. **Nothing survives the session unless it is in this repo.**

---

*PCR / Palisades — Confidential*
