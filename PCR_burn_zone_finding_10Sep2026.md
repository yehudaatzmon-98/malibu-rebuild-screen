# PCR / Palisades — The exit price moved and we were not measuring it

**For Tal · 10 September 2026 · Confidential**

---

## The finding

**HAVE.** Standing homes inside the fire footprint repriced down about **17%** after
7 January 2025. Homes outside the footprint did not move.

Every exit price in our model came from a pooled median of Palisades sales running
June 2023 to May 2026. That pool straddles the fire, and it mixes the burn footprint
with the Riviera, which largely stood. Pooling those hid the single largest movement
in the data.

Measured as a difference-in-differences on all 330 sales in the comp file, using Santa
Monica and Brentwood sales as an out-of-footprint control so ordinary Westside drift
is netted out:

| | Effect | 95% interval | p |
|---|---|---|---|
| Inside burn footprint, post-fire | **−17.1%** | −31.0% to −0.3% | 0.046 |
| Outside footprint, post-fire | +3.1% | −14.0% to +23.6% | 0.740 |
| Size elasticity | −0.242 per log foot | | <0.001 |
| New construction, ≤5 years | +9.4% | −1.2% to +21.3% | 0.085 |

n = 330. Bootstrap over 2,000 draws puts the discount between −29% and −4%, negative
in 98% of draws. Stable across every burn-boundary definition tried.

**Raw medians say the same thing.** Alphabet and Village went $1,245 to $1,082. The
west side went $1,471 to $1,141. The Riviera went $1,509 to $1,542.

## Two corrections to things we had already concluded

**The 4,000–4,500 sf trough is not real.** It was composition: that band held 23 older
houses against 5 new ones, and the 6,000+ band sits disproportionately in the Riviera.
Controlled, price per foot declines smoothly with size and there is no trophy recovery.
Total price still rises with size, as sf^0.758. **CORRECTION to the 9 Sep handover §3.**

**The new-build premium is smaller than we thought and cannot carry a pro forma.** The
19–26% figure was confounded the same way: new builds cluster in the Riviera, so the
raw premium was measuring location, not construction age. Controlled it is +9.4% with
an interval spanning zero. It is now defaulted to zero in the model and exposed as a
slider. **CORRECTION.**

## What it does to the numbers

Applied to a 3,800 sf flat Alphabet build at $1.1M land, $700/sf, 30-month schedule,
80% LTC with the interest reserve inside the loan:

| Burn recovery assumed | Exit $/sf | Profit | Breakeven land |
|---|---|---|---|
| 0% (carry the discount) | $1,034 | **−$885,000** | $246,000 |
| 50% | $1,140 | −$469,000 | $581,000 |
| 100% (full pre-fire recovery) | $1,247 | −$53,000 | $917,000 |

**Even assuming the burn zone fully recovers to pre-fire pricing, $1.1M land does not
work.** The discount is not the only problem, it is the one that turns a marginal deal
into a bad one.

Equity is also larger than the figure in circulation. On your own $3.6M framing, 20%
of land plus hard cost is $720K, but that number carries no interest. Solved properly,
with the reserve inside the loan, it is **$849K**. Fully loaded with soft costs,
contingency and carry, on a real 3,800 sf build, it is **$1.06M**. At 70% LTC, which
is closer to what a first-time sponsor without a completed ground-up development
actually gets, it is **$1.51M**.

## The three questions, in order of what they are worth

**1. Your read on whether burn-zone pricing recovers.** This is the whole business now.
Not a lot-selection problem. If the discount is a construction-site disamenity that
resolves as the neighbourhood rebuilds, the numbers look like the bottom row above. If
nearly 6,000 destroyed homes deliver 2,400-plus new houses into 2028–2030 and the
discount persists or deepens on absorption, there is no land price in the Palisades
that works. No dataset I have answers this. Your judgement does.

**2. Is the $700/sf hard cost or turnkey?** One question to your contact. If it already
includes architecture, engineering, permits and fees, then we are double-counting soft
costs and every breakeven land figure rises by roughly $80 per buildable foot. Worth
about $320K.

**3. The 1,142-sale comp file.** We have 330. The burn-zone discount rests on 24
post-fire sales inside the footprint, which is why the interval runs from −31% to
−0.3%. Your file would likely halve that interval, and the interval is currently the
difference between "proceed" and "do not".

Separately: **16614 Pequeno**, $990K ask, seller bought it burned in April 2025 at
$1.75M. Do you know why they are 43% under their own basis? And **16550 Akron**, $1M,
9,000 sf R1, no landslide, a 4,085 sf house built there in 2008 that burned. ZIMAS
calls it Hillside Area, but so does nearly every lot in the Palisades. On our numbers
it works nearer $435K to $775K, not $1M.

## Status

**GAP.** The burn footprint here is a longitude proxy, not the CAL FIRE perimeter.
Geocoding the comps against the published perimeter is the highest-value fix and needs
network access we do not have in the modelling environment.

**GAP.** Builder's risk insurance in a post-fire ZIP is unpriced and sits as a
placeholder in the carry line.

**COUNSEL, and now overdue.** Securities counsel, 506(b) versus 506(c). Open across
four documents. Investor conversations have begun and the election cannot be made
retroactively.

**Mandatory in any offering:** the builder is a partner in the transaction, so
construction pricing is not arm's length; and the sponsor has no completed ground-up
development as principal.

---

*PCR / Palisades — Confidential*
