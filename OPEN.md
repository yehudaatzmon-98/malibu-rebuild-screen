# OPEN — PCR / Palisades

Single source of truth for what is unresolved. Lives in the repo, changes by commit,
diffs instead of forking. **This file replaces the handover-document habit.** Handovers
duplicated, contradicted each other, and carried findings forward with more confidence
than the findings had earned. Three failed that way. If a claim is not in this file or
in the code, it is not current.

Last updated: 8 September 2026

---

## How to read this

Items are ordered by **what resolving them is worth**, not by how long they have been
open. That ordering is the thing that otherwise gets re-derived from scratch every
session.

Status tags: **HAVE** (established, sourced) · **DRAFT** (built, not verified) ·
**GAP** (missing input, work continues around it) · **COUNSEL** (lawyer, not us).

---

## 1 · Open items, by value

| # | Item | Worth | Status | With | Cost to resolve |
|---|---|---|---|---|---|
| 1 | **Burned / not-burned flag per parcel** | ~$810K of exit ambiguity on a 3,000 sf build | GAP | records | Fire perimeter is published; a parcel join, not a records request |
| 2 | **Written GMP or fixed-price bid** | Decides every pro forma downstream | GAP | Tal, open since 2 Sep | One conversation |
| 3 | **Does $700/sf include Chapter 7A** | ~$350K on a 2,700 sf build; closes or opens the whole hillside strategy | GAP | Tal / builder, sent 8 Sep | Free |
| 4 | **Securities counsel, 506(b) vs 506(c)** | Cannot be chosen retroactively; investor conversations have begun | COUNSEL | Tal, overdue | Independent of everything else |
| 5 | **16860 Livorno coastal conflict** | Dual permit disqualifies it under Tal's rule | GAP | anyone | CCC map lookup, free |
| 6 | **What is wrong with 16550 Akron** | $184/buildable ft, cheapest in Palisades, DOM 218 | GAP | Tal | Free |
| 7 | **Jacon geotech report** | Governs cost, and cost governs the lot | GAP | listing agent | Ask |
| 8 | **Insurance feasibility in a post-fire ZIP** | Builder's risk is unpriced in `Assumptions` | GAP | Tal | Broker call |
| 9 | **Malibu comparable sales** | Entire Malibu half of the analyzer returns NO COMPS by design | GAP | Tal | Data pull |

**Two disclosures are mandatory in any offering:** the builder is a partner in the
transaction, so construction pricing is not arm's length; and the sponsor has no
completed ground-up development as principal.

---

## 2 · Withdrawn findings

Recorded so they are not resurrected. All three shared one signature: **a median quoted
without inspecting the rows behind it.**

| Finding | Withdrawn | Why |
|---|---|---|
| 17% burn-zone discount | 8 Sep 2026 | Composition. Redfin lists a burned lot under the pre-fire house's square footage, so land trades read as cheap houses. |
| Size-band trough | 8 Sep 2026 | Composition. Post-fire size elasticity is +0.182 (p=0.011). Bigger sells for more per foot. Build to the envelope. |
| **Exit basis $1,542/sf, and the DiD +13.2%** | **8 Sep 2026** | **Selection on the outcome variable.** Reproduced exactly: of 134 post-fire Palisades SFR sales, deleting the 43 lowest by $/sf leaves n=91 at a $1,539 median. The pre-fire side was left uncut at $1,356. The premium is manufactured by the deletion. |

On the third: the classifier cut at $1,059/sf. 16597 Via Floresta at $1,059 was called
land; 735 Lachman Ln at $1,082 was called a house. They are indistinguishable. Neither
$/house-ft nor $/lot-ft separates land trades from standing homes in this data — the
first is unimodal and continuous, the second is defeated by Highlands parcels sitting on
400,000 sf common lots. **Only item 1 above resolves it. No classifier is encoded, by
choice.**

Current exit position: a range, bounded below by the uncut post-fire median (~$1,272,
too low because real land trades are in it) and above by the cut median ($1,539,
selection-inflated). For any specific lot, use the distance-gated comp match and verify
the six rows by hand.

---

## 3 · What is settled

- **ULA is permanent.** Repeal path closed 25 June 2026. Thresholds index to Chained CPI;
  at a 2030 exit tier 1 sits near $5.96M, so most lots in this size band clear it entirely.
- **Build timelines 30 to 35 months.** 501 Swarthmore 34, 16815 Livorno 35, from LADBS.
- **$700/sf is hard cost**, Tal adds 5% A&E. His own range was $600 to $800. Subject to item 3.
- **Storeys do not add area.** R1 caps floor area. Build up for site coverage, not size.
- **Redfin lot sizes are unreliable on cut parcels.** Two of nine were off by 2 to 4x. ZIMAS only.
- **Prior square footage from a sheet, listing or agent has been wrong 5 of 5**, always
  overstated. The C of O is the only authoritative source. `verified_records.csv` tags
  provenance per parcel; `ASSESSOR` is not verification.

---

## 4 · Lot status

Under Tal's rule for deal one — flat, no landslide, permit-friendly — the screen has now
returned **no deal across roughly a dozen lots.** That is a finding about the constraint,
not a run of bad luck, and it is the conversation to have with him.

| Lot | Ask | Verdict |
|---|---|---|
| 729 Swarthmore | $1,595,000 | Only clean lot found. Bid $1.3M. **Needs rerun against the rebuilt comps before any bid.** |
| 16742 Bollinger | $1,250,000 | Clean, 6.5% margin at ask. |
| 16827 W Sunset | $1,599,000 | Breakeven $1,704/sf vs $1,237 gated basis. Dead at ask. |
| 16860 Livorno | $1,600,000 | Breakeven $1,656/sf vs $1,307 gated basis. Dead at ask. Coastal conflict unresolved. |
| 826 Jacon Way | $1,350,000 | Works at or below $825/sf. Ruled out by the slope rule; reopenable. |
| 922 Enchanted Way | $1,795,000 | Works at or below $810/sf. Same. |
| 623 / 627 N Marquette | $990K / $999K | 623 works at 20% if the slope rule reopens. |
| 16550 Akron | $1,000,000 | See item 6. |
| 16150 Northfield, 558 Erskine, 1227 Bienveneda | — | Dead on the parcel record, 8 Sep. |
| 16503 Las Casas, 824 Chautauqua, 16614 Pequeno, 14511 Sunset, 1552/1555 Reseda, 1785 Alta Mura | — | Dead. |

Not yet pulled: 16521 Las Casas Pl · 1025 and 1067 Las Pulgas · 515 N Las Casas ·
676 N Las Casas · 16860 Livorno neighbours. First several likely landslide.

---

## 5 · Code state

`MARKET_VERSION` must read **m2.0**. If it reads m1.0 the withdrawn burn discount is live.

Fixed 8 Sep, all in this repo:

- **Comp matcher blended price tiers.** Distance carried 0.15 of the score, so a comp 3.45
  mi out scored within 0.006 of one 1.2 mi out. Pool is now gated by distance first
  (0.75 / 1.25 / 2 / 3 mi ladder), then scored, with the radius reported.
- **`parcel_hillside` was accepted and never read**, so a street-name substring set the
  cost band alone. ZIMAS now outranks the street list in both directions.
- **NaN square footage crashed the matcher** on 42 of the new rows.
- **No property-type filter** — a Highlands townhouse on a 137,962 sf common parcel was a comp.
- **241 of 1,184 rows have no sale date** and were scored as three years old. Now excluded.
- **Basis was a weighted mean**, so one $11.57M oceanfront sale moved a subject 42% away
  from its neighbour 0.1 mi up the street. Now a weighted median.

Still to do: remove the vestigial burn-recovery slider from `app.py`; archive the stale
`rebuild-screen/` fork; `screen.py` is superseded by `app.py`.

---

## 6 · Working rules that keep being relearned

1. **Look at the rows before quoting the number.** Every failed finding here broke this one.
2. **Verify before ranking.** Unverified figures have moved the wrong way every time.
3. **Comps are jurisdiction and tier segmented, never blended.** Distance is the observable
   proxy for tier in this data, and the gate now enforces it.
4. **Range, not verdict.** Show what you would have to believe.
5. **Separate measurement from bet.** Scarcity and burn-recovery stay labelled sliders at zero.
6. **State what is unknowable rather than estimating it.** Build structures that do not
   need the estimate. The land-trade split is the live example.
7. **Nothing survives the session unless it is in this repo.** Facts that took work go in a
   file before the session ends, or they did not happen.

---

*PCR / Palisades — Confidential*
