"""
Diligence card — the 30→5 worksheet.
====================================

The screener + money engine gets a batch down to a ranked shortlist. That cut is
a data problem and it's automatic. Getting the shortlist down to the few worth an
offer is a JUDGMENT problem, and it runs on facts no CSV holds: is the prior sqft
real, is it beachfront, are the comps actually comparable, can you tie the lot up,
and what unrecorded thing kills it.

A tool can't decide those. What it CAN do — and what makes Michael's life easy — is
hand him a filled-in worksheet per lot: what we already know, and a live link to
exactly where each unknown lives, ordered by how likely it is to kill the deal. He
works batches of 10-15 by calling agents and pulling records; this is the sheet he
keeps open next to the phone, checks off, and hands back to Tal.

Each item is one of:
  KNOWN   — answered from data we already pulled. No work.
  VERIFY  — we have a number but it's soft; here's the link to confirm it.
  FIND    — we don't have it; here's exactly where to get it.

Ordered by kill-likelihood, because Michael's time is the scarce thing: the item
most likely to end the deal goes first, so a dead lot dies on call one, not call five.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import urllib.parse


def _enc(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    return urllib.parse.quote_plus(str(address).strip())


@dataclass
class DiligenceItem:
    rank: int              # kill-order, 1 = most likely to end the deal
    question: str          # what Michael is answering
    status: str            # KNOWN / VERIFY / FIND
    have: str              # what we know now (may be empty)
    where: str             # link or instruction to resolve it
    kills_if: str          # the answer that ends the deal


def build_card(*, address: str, jurisdiction: str, prior_sqft: Optional[int],
               imp_value: Optional[int], is_beachfront: Optional[bool],
               units: Optional[int], matched_comps: Optional[list] = None,
               lot_flags: Optional[list] = None) -> list:
    """
    The per-lot checklist, kill-ordered. Returns a list of DiligenceItem.

    matched_comps: the comps the engine actually used, so Michael can eyeball the
                   3 a buyer's appraiser will lean on — with their Redfin URLs.
    lot_flags:     lot-specific killers surfaced by the screener (20314 separation,
                   20910 blank baseline, access cliff, etc.), passed straight through.
    """
    enc = _enc(address)
    items: list[DiligenceItem] = []

    # 1 — PRIOR SQFT REAL? Everything rests on it. The envelope, the cost, the return.
    if prior_sqft and imp_value and imp_value > 0:
        have = (f"County shows {prior_sqft:,} sf and taxes an improvement (${imp_value:,}), "
                f"so a structure existed. Number is the Assessor's, not a survey.")
        status = "VERIFY"
    elif prior_sqft:
        have = f"County shows {prior_sqft:,} sf, but no improvement value to corroborate it."
        status = "VERIFY"
    else:
        have = "No prior sqft in the county record. Blank cell, not a vacancy finding."
        status = "FIND"
    items.append(DiligenceItem(
        rank=1, question="Is the prior square footage real?",
        status=status, have=have,
        where=("Pre-fire listing (" +
               (f"https://www.redfin.com/city/search?q={enc}" if enc else "Redfin/Zillow") +
               ") states floor-by-floor; CAL FIRE DINS ('DINS 2025 Palisades Public View') "
               "recorded what stood on 7 Jan; seller's insurance replacement estimate is the "
               "gold copy. Ask the agent for the insurance file."),
        kills_if="Genuinely vacant — no baseline, no rebuild rights. Reprice or walk."))

    # 2 — BEACHFRONT? Forks the whole envelope (TDSF, SPR, access cliff, height basis).
    if jurisdiction == "MALIBU":
        if is_beachfront is None:
            items.append(DiligenceItem(
                rank=2, question="Beachfront or not?",
                status="FIND",
                have="Not in the county record. Forks everything: TDSF, SPR, height basis, "
                     "and the access cliff all flip on this.",
                where="City of Malibu GIS parcel layer, or stand on the lot. Free, one lookup.",
                kills_if="Beachfront + a plan over the 10% cap = permanent public-access "
                         "dedication risk. Changes what the exit buyer is buying."))
        else:
            items.append(DiligenceItem(
                rank=2, question="Beachfront or not?",
                status="KNOWN",
                have=("Beachfront — TDSF-exempt, no SPR, height from wave-action floor, but "
                      "the access cliff applies over 10%." if is_beachfront else
                      "Non-beachfront — TDSF binds, SPR above 18ft, no access cliff."),
                where="Confirmed. No action.",
                kills_if="—"))

    # 3 — ARE THE COMPS REAL? The database gives a basis; the winner needs the 3
    #     actual nearby sales an appraiser will use.
    if matched_comps:
        top = matched_comps[:3]
        lines = "; ".join(
            f"{c.get('address','?')} {c.get('sqft','?')}sf ${c.get('psf','?')}/sf {c.get('sold','?')}"
            for c in top)
        where = "Eyeball these on Redfin: " + " | ".join(
            c.get("url", c.get("address", "")) for c in top if c.get("url") or c.get("address"))
        items.append(DiligenceItem(
            rank=3, question="Do the exit comps actually resemble this lot?",
            status="VERIFY",
            have=f"Engine matched: {lines}",
            where=where,
            kills_if="The nearby real sales are materially below the matched basis — the "
                     "exit assumption doesn't hold and the ROC is fiction."))
    else:
        items.append(DiligenceItem(
            rank=3, question="Do the exit comps actually resemble this lot?",
            status="FIND",
            have="No matched comps (unpriceable market or missing envelope).",
            where="Pull 3 sold sales within ~0.25 mi at the target finished size.",
            kills_if="No comparable sales exist — you're guessing at exit."))

    # 4 — CAN YOU CONTROL IT? A great lot you can't tie up is worthless.
    items.append(DiligenceItem(
        rank=4, question="What's the real status — listed, LOI, option, or controlled?",
        status="FIND",
        have="Not in any record. The single most important factual gap after the baseline.",
        where=("Call the listing agent. Ask: still available, any offers in, will the seller "
               "do an option or a contingency period."),
        kills_if="Already under contract, or the seller won't grant time to run diligence."))

    # 5 — THE UNRECORDED KILLER. Lot-specific flags from the screener go here, plus
    #     the always-ask items.
    flag_text = ""
    if lot_flags:
        flag_text = " ".join(lot_flags)
    items.append(DiligenceItem(
        rank=5, question="What kills this that isn't in any record?",
        status="FIND",
        have=(flag_text or "No lot-specific flag from the screener — run the standard checks."),
        where=("Site visit: view corridor, access road, setback, debris/remediation status. "
               "Ask the seller: pre-fire permit application on file (PF1), did they take the "
               "fee waiver, any temporary-housing covenant. Make plan/survey delivery a PSA "
               "condition."),
        kills_if="Blocked view after neighbor rebuilds, no legal access, unresolved debris "
                 "lien, or a recorded covenant that transfers to you."))

    return items


def card_to_rows(address: str, items: list) -> list:
    """Flatten a card into export rows: one row per diligence item, with a blank
    'Michael's finding' column he fills in and hands back."""
    return [dict(
        Address=address, Priority=it.rank, Question=it.question,
        Status=it.status, **{"What we know": it.have},
        **{"Where to get it": it.where}, **{"Kills the deal if": it.kills_if},
        **{"Michael's finding": ""}, **{"Verified?": ""},
    ) for it in items]
