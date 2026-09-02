"""
Guide — the instructions, inside the tool.
==========================================

The written guide lived in a separate document, which meant the person using the
analyzer had the help in one window and the decision in another. Everything here
exists to close that gap. Three placements, in order of how much they matter:

1. THE LEGEND, above the ranked table. The single most important thing a user needs
   is not "how do I upload a CSV" — it is knowing that +26% margin over market is
   fatal and -2% is excellent. That belongs on screen at the moment of reading, not
   in a document.

2. COLUMN TOOLTIPS. Every column the guide explains gets its explanation attached to
   the column itself.

3. THE DRAWER. The full guide, always reachable from the sidebar, never in the way.

Design rule followed throughout: help appears where the decision is made. Nothing here
adds a step, a modal, or a page. Nothing here uses a colour or font not already in the
app's stylesheet.
"""
from __future__ import annotations
import streamlit as st


# ---------------------------------------------------------------- margin bands
# The interpretation that turns the headline number into a decision. Ordered worst
# to best left to right so the bar reads like a thermometer.
MARGIN_BANDS = [
    ("Above +25%", "Doesn't work", "var(--seal)",
     "No amount of negotiating fixes a gap this size."),
    ("+10% to +25%", "Tight", "var(--warn)",
     "Needs a strong market. Little room for error."),
    ("0% to +10%", "Good", "var(--info)",
     "New construction normally sells a little above average, so this clears on its own."),
    ("Negative", "Excellent", "var(--ok)",
     "Works even if the market does nothing."),
]


def render_margin_legend() -> None:
    """The band strip. Sits directly above the ranked table, always visible."""
    cells = "".join(
        f'<div style="flex:1;border-top:3px solid {colour};padding:8px 10px 0;">'
        f'<div class="lbl" style="color:{colour}!important;">{verdict}</div>'
        f'<div class="mono" style="font-size:0.82rem;font-weight:700;">{band}</div>'
        f'<div class="cite" style="font-size:0.74rem!important;line-height:1.4;">{note}</div>'
        f'</div>'
        for band, verdict, colour, note in MARGIN_BANDS)
    st.markdown(
        f'<div class="lbl" style="margin-bottom:6px;">Reading the margin over market</div>'
        f'<div style="display:flex;gap:14px;margin-bottom:6px;">{cells}</div>'
        f'<div class="cite" style="margin-bottom:14px;">How much higher than the normal '
        f'price on that street this house has to sell for, just to break even. '
        f'<b>A "Verified: no" near the top of the list is a property to go verify, not '
        f'a property to get excited about.</b></div>',
        unsafe_allow_html=True)


# ------------------------------------------------------------ column tooltips
# Attached to the ranked table via st.column_config. Every column the written guide
# explains is explained here instead, on the column itself.
COLUMN_HELP = {
    "Signal": "Quick verdict. STRONG or BUY clears the bar at asking price and is "
              "worth a call. MAYBE is marginal and only works if the price moves. "
              "PASS loses money at this price. NO COMPS, NEED PRICE and NEED PRIOR SF "
              "are data gaps, not rejections — the tool is refusing to guess.",
    "Margin over market": "The number that separates deals. Breakeven sale price "
                          "against the comparable median. Negative is excellent, 0 to "
                          "+10% is good, +10 to +25% is tight, above +25% does not "
                          "work. Not return on cost, which moves with whatever exit "
                          "price you assume.",
    "Verified": "Whether the prior square footage comes from a Certificate of "
                "Occupancy or original permit rather than a listing or a sheet. Five "
                "properties have been checked against City records and the listing "
                "figure was wrong on all five, always overstated. One by 57%.",
    "Breakeven $/sf": "What the finished house must sell for, per square foot, to "
                      "return zero. Compare it to the comparable median for that "
                      "street tier, not to the whole Palisades.",
    "Buildable sf": "How big a house we are allowed to build. The larger of the two "
                    "rebuild paths: EO1 like-for-like at 110% of footprint and "
                    "height, or EO8 zoning-compliant under LAMC.",
    "Ask": "The seller's asking price. Every number in this table is priced at full "
           "asking, which is the conservative floor.",
    "$/buildable ft": "What we pay per square foot of house we are allowed to build. "
                      "Lower is better. Under $350 is good.",
    "ROC": "Return on cost if every assumption holds. Read it second — it moves with "
           "whatever exit price you assume, which is why margin over market is the "
           "column that ranks.",
}


def apply_column_help(existing: dict) -> dict:
    """
    Merge the tooltips into whatever column_config the table already has, without
    clobbering the widgets already configured there (the star checkbox).
    """
    cfg = dict(existing)
    for col, text in COLUMN_HELP.items():
        if col in cfg:
            continue
        cfg[col] = st.column_config.TextColumn(help=text)
    return cfg


# -------------------------------------------------------------- the empty state
def render_start_here() -> None:
    """
    Three steps, horizontal, on the empty state. Replaces the two-column wall of
    prose, which said the same things at four times the length and pushed the sample
    button below the fold.
    """
    steps = [
        ("01", "Get the list",
         "Redfin → <b>For Sale</b> + <b>Land</b> → draw the burn zone with the map's "
         "Draw tool rather than typing an area name, which pulls in Brentwood and "
         "Santa Monica. Scroll to the bottom of the results and click "
         "<b>Download</b>. Redfin caps the export near 350 rows."),
        ("02", "Drop it in",
         "Use the <b>Redfin CSV</b> box above. Address, price, lot size and "
         "coordinates are read automatically. Nothing is typed per property. A long "
         "list takes about a minute, because every address is checked against "
         "LA County records while you wait."),
        ("03", "Read two columns",
         "<b>Margin over market</b> and <b>Verified</b>. Star anything promising, "
         "then pull its Certificate of Occupancy from lacitydbs.org and drop the PDF "
         "into <b>Verified records</b>. Each certificate makes the whole ranking "
         "more honest."),
    ]
    cols = st.columns(3, gap="medium")
    for col, (n, head, body) in zip(cols, steps):
        with col:
            st.markdown(
                f'<div class="card" style="height:100%;">'
                f'<div class="lbl">{n}</div>'
                f'<div style="font-family:Newsreader,Georgia,serif;font-size:1.15rem;'
                f'font-weight:700;margin:2px 0 6px;">{head}</div>'
                f'<div class="cite">{body}</div></div>',
                unsafe_allow_html=True)


# -------------------------------------------------------------------- the drawer
GUIDE_MD = """
### What this tool is for

We buy burned lots in Pacific Palisades and Malibu, rebuild, and sell the finished
houses. There are hundreds of lots for sale and most of them lose money. This tool
tells you which ones don't.

It answers two questions per property: can we legally build a big enough house on it,
and if we do, does the money work. It takes a list of 150 properties down to the
handful worth a phone call. It does not pick the winner. That part is a phone call and
a records check, and the tool tells you which ones to make.

---

### The three things you can upload

| Box | What goes in it | Where it comes from |
|---|---|---|
| **Redfin CSV** (main panel) | The list of lots to screen | Redfin search → For Sale + Land + drawn area → Download |
| **Verified records** (top) | Certificate of Occupancy PDFs | lacitydbs.org → search address → Certificate of Occupancy → save the PDF |
| **Add more comps** (sidebar) | Sold sales, to extend the comp set | Agent export or MLS pull, Palisades or Malibu |

They are three different files and they are not interchangeable. If a Malibu lot
returns NO COMPS, the fix is the third box, not the first.

---

### Verify before you get attached

The most valuable hour in the process, and it is free.

1. Go to **lacitydbs.org**, search the address
2. Click **Certificate of Occupancy** in the left menu
3. Open the PDF and save it
4. Glance at **Enforcement Cases**. Several means ask Yehuda
5. Drop the PDF into **Verified records** at the top of the tool

It reads the file and pulls the real square footage, height, storeys, basement, lot
size and Coastal Zone status. You type none of it. If the PDF will not read, older
certificates are photographs of paper rather than documents, so there is nothing to
extract. Paste the text instead, or send it to Yehuda.

---

### Underwriting one property

Four things to read on the single-property screen.

**What the investor receives.** How much goes in, how much comes back, over what
period.

**Does leverage help.** The same deal three ways. Watch both columns: the structure
with the best upside also has the worst downside.

**What breaks it.** Risks ranked by damage. On most properties the sale price and the
construction cost do roughly five times the damage of anything else. That is where to
spend effort.

**What to offer.** Rows are what we offer, columns are what the market does. Find the
column you actually believe, read down to the first offer that works. That is the bid.

---

### Then make the calls

Work the diligence checklist in order. It is sorted so the thing most likely to kill
the deal comes first, because a dead property should die on the first check and not
the fifth.

1. Was there really a house here? (5 min, online)
2. Is it in the Coastal Zone? (2 min, online)
3. Do the comparable sales hold up? (5 min, online)
4. Can we buy it, at a price that works? (one call to the listing agent)
5. Anything that would wreck it that is not in the records? (site visit)

The checklist gives you the words for the agent call and the walk-away price to hold
in your head before you dial.

---

### Two things to remember

**Unverified numbers are wrong in the same direction.** Five out of five so far, every
one making the deal look better than it was. A property that looks great and says
"Verified: no" is a signal to check, not to celebrate.

**The tool is a filter, not a decision.** It gets 150 properties down to about 10
honestly. Getting those 10 to the one we buy takes phone calls, a site visit and
judgement. The tool's job is to make sure that effort goes on the right ten.

*Questions to Yehuda. Nothing here is final until the records confirm it.*
"""


def render_guide_drawer() -> None:
    """
    Full guide in the sidebar, collapsed. Reachable from every screen including the
    single-property view, where the empty-state help is long gone.
    """
    with st.sidebar.expander("Guide — how to use this"):
        st.markdown(GUIDE_MD)
