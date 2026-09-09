# OPEN — PCR / Palisades

Single source of truth for what is unresolved. Lives in the repo, changes by commit,
diffs instead of forking. **This file replaces the handover-document habit.** Handovers
duplicated, contradicted each other, and carried findings forward with more confidence
than the findings had earned. Three failed that way. If a claim is not in this file or
in the code, it is not current.

Last updated: 8 September 2026 (second revision: Swarthmore comps verified, Livorno coastal triaged, GMP and 7A merged, investor item corrected)

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
| 2 | **Builder's price in writing**, against a defined scope and sqft, inclusions and exclusions listed. **Chapter 7A is one line on that list**, not a separate item. A true GMP needs drawings we do not have, so this is the realistic ask | Construction is $2.35M of a $5.1M cost and currently rests on a verbal number. Decides every pro forma | GAP | Tal, open since 2 Sep; 7A line sent 8 Sep | One conversation |
| 3 | **Securities counsel, 506(b) vs 506(c)** | Cannot be chosen retroactively. **Corrected 8 Sep: investor conversations have NOT begun.** Not urgent, but it is a gate in front of the first conversation, not after a bid, and if the deal needs outside money those conversations start around the bid | COUNSEL | Tal | Independent of everything else |
| 4 | **What is wrong with 16550 Akron** | $184/buildable ft, cheapest in Palisades, DOM 218 | GAP | Tal | Free |
| 5 | **Jacon geotech report** | Governs cost, and cost governs the lot | GAP | listing agent | Ask |
| 6 | **Insurance feasibility in a post-fire ZIP** | Builder's risk is unpriced in `Assumptions` | GAP | Tal | Broker call |
| 7 | **Malibu comparable sales** | Entire Malibu half of the analyzer returns NO COMPS by design | GAP | Tal | Data pull |

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
| 729 Swarthmore | $1,595,000 | **Comps hand-verified 8 Sep, see section 4a. Needs the 75th percentile of its own tier to break even at ask. The $1.3M bid returns -4.5% at the tier median. Do not bid at $1.3M.** |
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

## 4a · 729 Swarthmore, comps verified by hand (8 Sep)

The matcher returned a $1,584 basis. Three of its six comps are off-tier: 14929 and
14959 La Cumbre Dr are Riviera, and they are what lifted it. The distance gate is a good
tier proxy in Castellammare, where tiers are geographically separated, and a weak one in
the Village, where the Riviera sits half a mile away.

Tier-matched set: Alphabet and Village streets only, within 1.0 mi, 2,100 to 3,400 sf.
**n=44, median $1,456/sf, quartiles $1,276 to $1,688.** Only **three** of those 44 sold
post-fire, at $1,159, $1,869 and $2,427. There is no post-fire depth in this tier and
size band, and that is the real constraint on the bid.

Envelope 2,699 sf, construction $700/sf, breakeven sale **$1,827/sf**.

| Exit | ROC at $1,595,000 ask | ROC at $1.3M bid | Margin over market required |
|---|---|---|---|
| 25th pct $1,276 | -23.1% | -16.3% | +43% |
| Median $1,456 | -12.3% | **-4.5%** | +26% |
| 75th pct $1,688 | +1.7% | +10.7% | +8% |

Land that clears each hurdle at the tier median: 0% at $1,149,000, 10% at $860,000,
15% at $734,000, 20% at $619,000.

**Conclusion: $1.3M is not a breakeven bid, it is a 13% overpay against breakeven.**
Breakeven land is $1.15M and a 15% deal needs $734K. The lot only works at ask if the
Palisades Alphabet tier is at its own 75th percentile at exit, which is a bet, not a
measurement.

---

## 4b · 16860 Livorno coastal conflict, likely resolved (8 Sep)

ZIMAS lists both Dual and Single Permit Jurisdiction on this parcel. Dual Permit
Jurisdiction is defined by PRC Section 30601: within 300 ft of the beach or sea, within
100 ft of a stream, or within 300 ft of the top of the seaward face of a coastal bluff.
16860 Livorno returns No on Coastal Bluff Potential, No on Canyon Bluff Potential, No on
Watercourse and No on Streams, and it sits inland of Sunset. It meets no 30601 trigger,
so the dual listing reads as a mapping artifact rather than a determination.

Corroboration: 17405 Castellammare, which is in our comp set, IS in the Dual Permit
Jurisdiction per CCC staff report 5-13-0771. The dual zone runs along the seaward bluff
side, not up into Lower Marquez Knolls.

**Not authoritative.** The only body that can confirm is the CCC South Coast District
Office, (562) 590-5071 or SouthCoast@coastal.ca.gov. One call. Worth making only if the
lot comes back into play, which at -13.1% at ask it has not.

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
