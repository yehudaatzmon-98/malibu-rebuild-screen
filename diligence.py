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
    do_now: str = ""       # the ONE action to take, imperative
    ask_verbatim: str = "" # the exact words to say on a call, if this is a call step
    minutes: str = ""      # rough time cost, so he can plan the batch


def build_card(*, address: str, jurisdiction: str, prior_sqft: Optional[int],
               imp_value: Optional[int], is_beachfront: Optional[bool],
               units: Optional[int], matched_comps: Optional[list] = None,
               lot_flags: Optional[list] = None, breakeven: Optional[str] = None) -> list:
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
        have = (f"County shows {prior_sqft:,} sf and taxes a building worth ${imp_value:,}, "
                f"so a house almost certainly stood here. Good sign — but confirm.")
        status = "VERIFY"
    elif prior_sqft:
        have = (f"County shows {prior_sqft:,} sf, but no building value on the tax roll to "
                f"back it up. Might just be a records gap — but confirm a house was here.")
        status = "VERIFY"
    else:
        have = "County shows no square footage. Could be a records gap, could be empty land."
        status = "FIND"
    items.append(DiligenceItem(
        rank=1, question="Was there really a house here before the fire?",
        status=status, have=have, minutes="5 min, online",
        do_now=("Open the pre-fire Redfin/Zillow listing for this address and check it "
                "describes an actual house (beds, baths, floors). If the listing is gone, "
                "search CAL FIRE DINS ('DINS 2025 Palisades Public View') for the address."),
        where=(f"Redfin: https://www.redfin.com/city/search?q={enc}" if enc else
               "Search the address on Redfin/Zillow") +
              "   ·   DINS: search 'DINS 2025 Palisades Public View'",
        kills_if="It was always empty land — no house ever built. Then there are no rebuild "
                 "rights and the whole deal falls apart. Drop it or offer raw-land price.",
        ask_verbatim=""))

    # 2 — BEACHFRONT? Malibu only. Forks the whole envelope.
    if jurisdiction == "MALIBU":
        if is_beachfront is None:
            items.append(DiligenceItem(
                rank=2, question="Is this lot right on the beach?",
                status="FIND", minutes="2 min, online",
                have="Not in the county record, and it changes everything about what you can "
                     "build. Must confirm.",
                do_now="Look at the lot on a map. Does it front the sand directly, or is there "
                       "a road/row of houses between it and the water?",
                where="City of Malibu GIS map, or just Google Maps satellite view.",
                kills_if="If it's beachfront AND you want to build more than 10% bigger, you "
                         "can be forced to give the public a permanent walkway across the lot. "
                         "That scares off your eventual buyer.",
                ask_verbatim=""))

    # 3 — DO THE COMPS HOLD UP? The exit price is the whole return.
    if matched_comps:
        top = matched_comps[:3]
        lines = "; ".join(
            f"{c.get('address','?')} ({c.get('sqft','?')} sf, ${c.get('psf','?')}/sf, "
            f"sold {c.get('sold','?')})" for c in top)
        urls = " | ".join(c.get("url", c.get("address", ""))
                          for c in top if c.get("url") or c.get("address"))
        items.append(DiligenceItem(
            rank=3, question="Will the finished house actually sell for what we assumed?",
            status="VERIFY", minutes="5 min, online",
            have=f"The return is based on these 3 recent nearby sales: {lines}",
            do_now="Open the 3 sales below and sanity-check they're genuinely similar — same "
                   "kind of street, similar size, recent. If they look like nicer or bigger "
                   "homes than what you'd build here, the exit price is too optimistic.",
            where=f"Pull these up on Redfin: {urls}",
            kills_if="The real nearby sales are clearly cheaper than the tool assumed — then "
                     "the profit is fiction and the ranking is wrong for this lot.",
            ask_verbatim=""))
    else:
        items.append(DiligenceItem(
            rank=3, question="Will the finished house actually sell for what we assumed?",
            status="FIND", minutes="10 min, online",
            have="No comps matched (Malibu lot, or missing data).",
            do_now="Pull 3 recent sold homes within about a quarter-mile, similar size, and "
                   "note their price per square foot.",
            where="Redfin → filter to Sold, draw a small circle around the lot.",
            kills_if="No comparable sales exist nearby — you're guessing at the exit price.",
            ask_verbatim=""))

    # 4 — CAN YOU ACTUALLY BUY IT, AT A PRICE THAT WORKS? The agent call.
    walk = f" {breakeven}." if breakeven else "."
    items.append(DiligenceItem(
        rank=4, question="Can we actually tie it up — and at a price that still profits?",
        status="FIND", minutes="1 call, ~10 min",
        have=(f"This is the phone call. Before you dial, know your ceiling:{walk} "
              f"If the seller won't get near that, it's not worth pursuing."),
        do_now="Call the listing agent. Use the script on the right. If they say it's already "
               "in escrow, or the seller wants full price and won't give you time to check "
               "things, cross it off and move to the next lot.",
        where="Listing agent — number is on the Redfin/Zillow listing.",
        ask_verbatim=("\"Hi, I'm calling about [address]. Is it still available? "
                      "Are there any offers in right now? "
                      "Is the seller open to an option period or a short due-diligence window "
                      "before closing? And is there any flexibility on the asking price?\""),
        kills_if="Already under contract, seller won't grant any diligence time, or won't "
                 "move enough on price to leave a profit."))

    # 5 — HIDDEN KILLERS. Lot-specific flags plus the always-ask seller questions.
    flag_text = ""
    if lot_flags:
        flag_text = " ".join(lot_flags) + " "
    items.append(DiligenceItem(
        rank=5, question="Anything that could wreck it that isn't in the records?",
        status="FIND", minutes="site visit + seller Qs",
        have=(flag_text + "These don't show up online — they need eyes on the lot and a few "
              "direct questions to the seller."),
        do_now="If the lot survived steps 1–4, drive by (or have someone photograph it) and "
               "ask the seller the questions on the right. Put 'seller delivers all plans, "
               "surveys, and permits' in the purchase contract.",
        where="Drive-by + questions to the seller/agent.",
        ask_verbatim=("Ask the seller: \"Did you have any permit or addition application filed "
                      "before the fire? Did you take the city's fee waiver? Is there a trailer "
                      "or temporary-housing agreement on the lot? Has debris been cleared?\""),
        kills_if="View gets blocked when neighbors rebuild, no legal road access, an unpaid "
                 "debris lien, or a recorded agreement that transfers to you as the buyer."))

    return items


def card_to_rows(address: str, items: list) -> list:
    """Flatten a card into export rows for the worksheet — one row per step, in order,
    with a blank column for what Michael finds and a done checkbox."""
    return [dict(
        Address=address, Step=it.rank, **{"Do this": it.do_now or it.question},
        **{"Time": it.minutes}, **{"What we already know": it.have},
        **{"Exactly what to ask / where": (it.ask_verbatim or it.where)},
        **{"Drop the lot if": it.kills_if},
        **{"What I found": ""}, **{"Done?": ""},
    ) for it in items]
