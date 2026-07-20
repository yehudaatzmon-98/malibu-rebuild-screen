"""
LA County Assessor parcel enrichment
=====================================
Live public endpoint, no auth, updated weekly:
  https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0

This is the layer that turns a Redfin export (which has NO prior square footage —
burned lots show dashes across beds/baths/sqft) into something the Interp. No. 24
envelope math can actually run on.

Fields pulled and why each matters:
  SQFTmain1..5    prior square footage — the input the entire model rests on
  YearBuilt1..5   drives the prior ceiling-height estimate (the volume ceiling)
  Units1..5       NO NET LOSS detector (Interp 24 Issue 8 / SB 166). This is what
                  took a human reading the rule to catch on 20314 PCH. Now a column.
  UseCode/UseDescription   eligibility triage
  DesignType1..5  multiple structures per parcel = Issue No. 7 (combining sqft)
  CENTER_LAT/LON  real geocodes. No more fabricated coordinates.
  Shape.STArea()  lot size from the parcel polygon, not a listing claim

The address join is CLEAN, not fuzzy: SitusHouseNo is a separate field, so we match
on house number exactly and street with a LIKE. No string-similarity guessing.

NOTE: every value returned here is tagged SOURCED. Values that disagree with the
listing are flagged, not reconciled — see Interp. No. 24 Issue No. 12, which requires
a survey at Planning Verification precisely because Assessor and plans disagree.
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import Optional
import requests

import jurisdiction as jur

ENDPOINT = ("https://public.gis.lacounty.gov/public/rest/services/"
            "LACounty_Cache/LACounty_Parcel/MapServer/0/query")

OUT_FIELDS = ",".join([
    "AIN", "APN", "SitusHouseNo", "SitusStreet", "SitusFullAddress", "SitusCity",
    "UseCode", "UseType", "UseDescription",
    "DesignType1", "YearBuilt1", "Units1", "Bedrooms1", "Bathrooms1", "SQFTmain1",
    "DesignType2", "YearBuilt2", "Units2", "SQFTmain2",
    "DesignType3", "YearBuilt3", "Units3", "SQFTmain3",
    "Roll_Year", "Roll_LandValue", "Roll_ImpValue",
    "CENTER_LAT", "CENTER_LON",
    # Lot size from the parcel polygon rather than a listing claim. The docstring
    # promised this and never fetched it. If the layer rejects the name the query
    # still succeeds — see _to_parcel, which treats it as optional.
    "Shape.STArea()",
])

# LA County use codes — the ones that matter for this regime.
# 01xx = single family, 02xx = 2 units, 03xx = 3 units, 04xx = 4+ units,
# 05xx = 5+/apartments, 010V/0100 vacant.
SFR_PREFIXES = ("010",)
MULTI_PREFIXES = ("02", "03", "04", "05", "06", "07", "08")


@dataclass
class Parcel:
    found: bool
    ain: Optional[str] = None
    situs: Optional[str] = None
    situs_city: Optional[str] = None      # drives jurisdiction routing — see jurisdiction.py
    use_code: Optional[str] = None
    use_desc: Optional[str] = None
    prior_sqft: Optional[int] = None        # sum across structures
    sqft_by_structure: list = field(default_factory=list)
    year_built: Optional[int] = None
    units: Optional[int] = None
    beds: Optional[int] = None
    baths: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    lot_sqft: Optional[int] = None        # from the parcel polygon, not a listing claim
    n_structures: int = 0
    land_value: Optional[int] = None
    imp_value: Optional[int] = None
    note: str = ""


def _norm_street(s: str) -> str:
    """Normalize a street name for the LIKE clause. County uses abbreviations."""
    s = str(s).upper().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    # 'PCH' is how everyone writes it; the county stores 'PACIFIC COAST HWY'
    if re.fullmatch(r"PCH", s):
        s = "PACIFIC COAST HWY"
    # county stores 'PACIFIC COAST HWY' — strip the common suffix variants so the
    # LIKE matches regardless of which the listing used
    for long, short in [("HIGHWAY", "HWY"), ("BOULEVARD", "BLVD"), ("AVENUE", "AVE"),
                        ("STREET", "ST"), ("DRIVE", "DR"), ("ROAD", "RD"),
                        ("PLACE", "PL"), ("TERRACE", "TER"), ("LANE", "LN"),
                        ("COURT", "CT"), ("CIRCLE", "CIR"), ("WAY", "WAY")]:
        s = re.sub(rf"\b{long}\b", short, s)
    return s


def split_address(addr: str):
    """'20610 Pacific Coast Hwy' -> ('20610', 'PACIFIC COAST HWY')"""
    a = str(addr).strip()
    m = re.match(r"^\s*(\d+)\s*(?:1/2)?\s+(.*)$", a)
    if not m:
        return None, None
    house = m.group(1)
    street = _norm_street(m.group(2))
    # drop unit designators — county keeps those in SitusUnit
    street = re.split(r"\s+(?:#|UNIT|APT)\b", street)[0].strip()
    return house, street


def lookup(address: str, city: Optional[str] = None, timeout: int = 20,
           retries: int = 2) -> Parcel:
    """
    Query the county for one address. Clean join: exact house number, LIKE street.
    Returns Parcel(found=False) rather than raising — a miss is data, not an error.

    city defaults to None — DO NOT restore a default here.
    ------------------------------------------------------
    This parameter previously defaulted to "MALIBU", which silently appended
        AND SitusCity LIKE 'MALIBU%'
    to every single-address query. Any parcel outside Malibu returned zero
    features and reported "No county parcel matched" — indistinguishable from an
    address the county genuinely doesn't hold. Two valid Pacific Palisades
    addresses (16767 Bollinger Dr, 1303 Marinette Rd) failed this way.

    House number + street is close to unique across the county, so we query
    unfiltered and disambiguate on the SitusCity that comes BACK. Jurisdiction is
    an output of the record, never an input from the caller.
    """
    house, street = split_address(address)
    if not house:
        return Parcel(False, note=f"Could not parse address: {address!r}")

    # Distinctive part of the street for the LIKE. Two words covers the common
    # cases ('PACIFIC COAST HWY' -> 'PACIFIC COAST'), but streets whose
    # distinguishing word is third ('N LAS CASAS AVE' -> 'N LAS') truncate badly,
    # so drop a leading directional first.
    parts = street.split()
    if parts and parts[0] in ("N", "S", "E", "W"):
        parts = parts[1:]
    core = " ".join(parts[:2]) if len(parts) > 1 else (parts[0] if parts else street)

    where = f"SitusHouseNo = '{house}' AND SitusStreet LIKE '{core}%'"
    if city:
        # Only ever applied when a caller explicitly passes a city (e.g. a Redfin
        # CITY column). Never defaulted.
        where += f" AND SitusCity LIKE '{str(city).upper()}%'"

    params = {"where": where, "outFields": OUT_FIELDS, "returnGeometry": "false",
              "f": "json", "resultRecordCount": 5}

    last = ""
    for attempt in range(retries + 1):
        try:
            r = requests.get(ENDPOINT, params=params, timeout=timeout)
            r.raise_for_status()
            js = r.json()
            if "error" in js:
                return Parcel(False, note=f"County API error: {js['error'].get('message','?')}"
                                          f"<br><span class='cite'>query: {where}</span>")
            feats = js.get("features", [])
            if not feats:
                # Echo the WHERE clause. A failure you can't read is a failure you
                # can't diagnose — this is exactly how the MALIBU filter hid.
                return Parcel(False, note=(
                    f"No county parcel matched.<br>"
                    f"<span class='cite'>query: {where}</span><br>"
                    f"Parsed as house '{house}', street '{core}'. If the address is real, "
                    f"the street parse or a city filter is likely at fault."))
            if len(feats) > 1:
                # Previously took feats[0] silently out of up to 5 matches.
                cands = [f["attributes"].get("SitusFullAddress") or "?" for f in feats]
                p = _to_parcel(feats[0]["attributes"])
                p.note = (f"AMBIGUOUS: {len(feats)} parcels matched; using the first. "
                          f"Candidates: {', '.join(str(c) for c in cands[:5])}")
                return p
            return _to_parcel(feats[0]["attributes"])
        except Exception as e:
            last = str(e)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    return Parcel(False, note=f"County lookup failed after {retries+1} tries: {last}"
                             f"<br><span class='cite'>query: {where}</span>")


def _lot_area(a: dict) -> Optional[int]:
    """
    Lot size from the parcel polygon. The layer may expose this under a few names
    depending on how the service was published, so try them all and treat absence
    as data rather than error.
    """
    for k in ("Shape.STArea()", "Shape_Area", "Shape.area", "SHAPE.STArea()"):
        v = a.get(k)
        if v:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                continue
    return None


def _to_parcel(a: dict) -> Parcel:
    sqfts, years, units, designs = [], [], [], []
    for i in (1, 2, 3):
        s = a.get(f"SQFTmain{i}")
        if s:
            sqfts.append(int(s))
            y = a.get(f"YearBuilt{i}")
            if y and str(y).strip() not in ("", "0"):
                years.append(int(y))
            u = a.get(f"Units{i}")
            if u:
                units.append(int(u))
            designs.append(a.get(f"DesignType{i}"))

    total_sqft = sum(sqfts) if sqfts else None
    # Issue No. 7: multiple structures may be combinable, but the SUM is what the
    # 110% applies to. Report both the total and the breakdown.
    return Parcel(
        found=True,
        ain=a.get("AIN"),
        situs=a.get("SitusFullAddress") or a.get("SitusStreet"),
        situs_city=a.get("SitusCity"),
        use_code=a.get("UseCode"),
        use_desc=a.get("UseDescription"),
        prior_sqft=total_sqft,
        sqft_by_structure=sqfts,
        year_built=min(years) if years else None,
        units=sum(units) if units else None,
        beds=a.get("Bedrooms1"),
        baths=a.get("Bathrooms1"),
        lat=a.get("CENTER_LAT"),
        lon=a.get("CENTER_LON"),
        lot_sqft=_lot_area(a),
        n_structures=len(sqfts),
        land_value=a.get("Roll_LandValue"),
        imp_value=a.get("Roll_ImpValue"),
    )


# ---------------------------------------------------------------- triage
@dataclass
class Triage:
    verdict: str      # ELIGIBLE | EXCLUDED | UNSCOREABLE | REVIEW
    reason: str
    rule: str = ""
    jurisdiction: str = ""   # MALIBU | CITY_OF_LA | UNKNOWN


def _discrepancy(p: Parcel, listing_sqft) -> Optional[str]:
    """
    Listing-vs-county prior square footage gap.

    This is the single most reliably valuable check the tool performs, and it is
    jurisdiction-independent — the county record is the county record regardless
    of which rulebook governs the rebuild.

    Observed, live, 17 Jul 2026:
      20048 PCH (Malibu)      listing 2,452 sf vs county 1,671 sf  -> +47% overstated
      16767 Bollinger (LA)    listing 4,527 sf vs county 3,339 sf  -> +36% overstated

    Two lots, two markets, both listings inflating what burned. Prior square
    footage is the input that sets the rebuild envelope in BOTH regimes, and it is
    the number almost no buyer checks. A listing is a marketing document. The
    county roll is a record. Model the record.
    """
    if not (listing_sqft and p.prior_sqft):
        return None
    try:
        ls = float(listing_sqft)
    except (TypeError, ValueError):
        return None
    if ls <= 0 or ls != ls:  # ls != ls catches nan (blank sqft on a vacant-lot listing)
        return None
    gap = (ls - p.prior_sqft) / p.prior_sqft
    if abs(gap) <= 0.10:
        return None
    direction = "OVERSTATES" if gap > 0 else "understates"
    msg = (f"<b>DISCREPANCY — listing {direction} what burned.</b> Listing claims "
           f"{ls:,.0f} sf; county roll shows {p.prior_sqft:,} sf ({gap:+.0%}).")
    if gap > 0:
        msg += (f" That is {ls - p.prior_sqft:,.0f} sf of envelope the listing is "
                f"selling and the record does not support. Model the county figure.")
    # The survey requirement is jurisdiction-specific — don't cite Malibu's
    # interpretation at an LA parcel.
    if jur.route(p.situs_city).code == jur.MALIBU:
        msg += (" A survey is required at Planning Verification precisely because "
                "Assessor and plans disagree [Interp. No. 24, Issue No. 12].")
    else:
        msg += (" Establish the prior envelope from issued permits, the Certificate of "
                "Occupancy, or the LADBS Rebuild Letter before underwriting it.")
    return msg


def triage(p: Parcel, listing_sqft=None, listing_price=None, storeys=None) -> Triage:
    """
    Eligibility screen. Routes by jurisdiction FIRST, then applies that
    jurisdiction's rule — never a default one.

    Interpretation No. 24 is Malibu law. It has no force in the City of LA.
    Applying it to a Palisades parcel would invent a volume constraint that does
    not legally exist there and haircut an envelope that isn't capped. That is a
    worse failure than the lookup error it would replace: the tool would stop
    erroring and start lying.
    """
    if not p.found:
        return Triage("UNSCOREABLE", p.note or "No county record matched.")

    j = jur.route(p.situs_city)

    # Jurisdiction gate — before any rule is applied.
    if j.code == jur.UNKNOWN:
        return Triage("UNSCOREABLE", j.note, "", j.code)

    if j.code == jur.CITY_OF_LA:
        # The rule is known and cited. With prior gross sqft we CAN compute a base
        # EO1 envelope (rebuild same massing = prior x 1.10) — no footprint needed.
        # Only the storey-add upside needs footprint, and that's flagged as upside.
        note = jur.la_review_note(p.prior_sqft, p.year_built, storeys, address=p.situs or None)
        d = _discrepancy(p, listing_sqft)
        if d:
            note = f"{d}<br><br>{note}"
        verdict = "SCOREABLE" if p.prior_sqft else "REVIEW"
        return Triage(verdict, note, j.rulebook, j.code)

    # --- City of Malibu: Interpretation No. 24 ---
    if not p.prior_sqft:
        return Triage("UNSCOREABLE", no_prior_sqft_note(p),
                      "Interp. No. 24, Issue No. 4", jur.MALIBU)

    if p.units and p.units > 1:
        return Triage(
            "EXCLUDED",
            f"County shows {p.units} units. Converting multifamily to a single-family "
            f"home triggers No Net Loss — the lost units must be replaced as ADUs, "
            f"which consume envelope.<br><br>"
            f"<b>But No Net Loss isn't the binding constraint — 'same use' is, and it's "
            f"structurally prior.</b> LIP 13.4.6(A)(1) is a threshold criterion of the "
            f"exemption itself: <i>\"It is for the same use as the destroyed structure.\"</i> "
            f"Triplex to single-family is a use change. Fail it and Issue No. 8 never engages, "
            f"because there's no exemption left to condition — you're at a full CDP.<br><br>"
            f"<b>How granularly does Malibu read 'use'? Issue No. 7 answers it:</b> <i>\"If an "
            f"uninhabitable structure (such as a garage) is combined with a habitable "
            f"structure, the square footage of the uninhabitable area must be "
            f"maintained.\"</i> The City polices habitable-vs-uninhabitable <i>within a single "
            f"residence</i> as a use distinction. If garage-vs-house is a use difference, "
            f"triplex-vs-SFR isn't close.<br><br>"
            f"<b>Which reframes the ADU remedy.</b> Issue No. 8's ADUs aren't a No Net Loss "
            f"workaround — they're plausibly a <i>same-use</i> workaround. Three dwelling units "
            f"to three dwelling units preserves density and use at once. That's why the fix is "
            f"ADUs rather than an in-lieu fee: a fee would satisfy SB 166 and do nothing for "
            f"13.4.6(A)(1).<br><br>"
            f"<b>So: SFR + 2 ADUs (or three homes) likely clears both gates. One house fails "
            f"both.</b><br>"
            f"<span class='cite'>The counter for counsel to argue: 'use' in PRC 30610(g) may "
            f"mean the broad Coastal Act category — residential vs commercial — since the "
            f"statute's concern is resource intensity, not zoning taxonomy. Probably loses "
            f"against Issue No. 7's text, but it's the argument. And verify structure "
            f"separations: over 10ft apart and Issue No. 7 forecloses combining regardless.</span>",
            "Interp. No. 24, LIP 13.4.6(A)(1) / Issue No. 8", jur.MALIBU)

    uc = str(p.use_code or "")
    if uc.startswith(MULTI_PREFIXES):
        return Triage("EXCLUDED",
                      f"Use code {uc} ({p.use_desc}) indicates multifamily. See No Net Loss.",
                      "Interp. No. 24, Issue No. 8", jur.MALIBU)

    flags = []
    if p.n_structures > 1:
        flags.append(
            f"{p.n_structures} structures on parcel ({', '.join(str(s) for s in p.sqft_by_structure)} sf). "
            f"Combining is permitted only if they were <=10ft apart and the use is maintained; "
            f"uninhabitable sqft must stay uninhabitable [Issue No. 7].")

    d = _discrepancy(p, listing_sqft)
    if d:
        flags.append(d)

    return Triage("ELIGIBLE",
                  " | ".join(flags) if flags else
                  f"Single-family, {p.prior_sqft:,} sf prior, built {p.year_built}.",
                  "Interp. No. 24, Issue No. 1", jur.MALIBU)


# ---------------------------------------------------------------- envelope
def ceiling_from_year(yr: Optional[int], override: Optional[float] = None):
    """
    Prior ceiling height. THE SOFTEST LOAD-BEARING NUMBER IN THIS TOOL.

    ---------------------------------------------------------------------------
    READ THIS BEFORE TRUSTING ANY MALIBU ENVELOPE THIS TOOL PRINTS
    ---------------------------------------------------------------------------
    The year->height mapping below is NOT SOURCED. It was chosen for plausibility,
    not derived from a construction-history reference, a survey, or the county
    record. The county does not publish ceiling height at all.

    It drives the volume ceiling, which is the tool's headline finding. On 20838
    PCH, correcting this one input moved the envelope 19%. Every Malibu number
    downstream of it inherits its uncertainty.

    It is kept because the alternative — refusing to compute any Malibu envelope
    at all — is less useful than computing one and labelling it honestly. But it
    is a bracket, not a measurement.

    HOW TO KILL THIS ASSUMPTION, in order of cost:
      1. The pre-fire sale listing. Luxury copy brags about ceiling height
         ("soaring 12-foot ceilings", "volume ceilings"). Free, instant, and the
         same trick that gives you storey count on the LA branch.
      2. Tal's own knowledge of the block. He walked David's house. Use `override`.
      3. Original plans or the survey required at Planning Verification
         [Issue No. 12]. Definitive, slow.

    Returns (height_ft, basis_string). The basis string travels with the output so
    a reader always sees where the number came from.
    """
    if override:
        return float(override), f"SUPPLIED — {override}ft, entered by you, not estimated"
    if not yr:
        return None, "UNKNOWN — no year built, envelope not computed"
    if yr < 1950:
        return 8.0, (f"ESTIMATED — UNSOURCED. Year built {yr}; assumed ~8ft for pre-1950 "
                     f"stock. Not from any record. Check the pre-fire listing.")
    if yr < 2000:
        return 8.5, (f"ESTIMATED — UNSOURCED. Year built {yr}; assumed ~8.5ft for "
                     f"mid-century stock. Not from any record. Check the pre-fire listing.")
    return 9.5, (f"ESTIMATED — UNSOURCED. Year built {yr}; assumed ~9.5ft for modern "
                 f"stock. Not from any record. Check the pre-fire listing.")


def ceiling_sensitivity(prior_sqft: float, proposed_ceiling: float,
                        basement_sqft: float = 0.0):
    """
    What the Malibu envelope would be across the plausible range of prior ceiling
    heights. Since prior_ceiling is unsourced, a point estimate conveys false
    precision — this shows the reader how much the guess is carrying.
    """
    out = []
    for h in (8.0, 8.5, 9.0, 9.5, 10.0):
        e = envelope(prior_sqft, h, proposed_ceiling, basement_sqft)
        out.append(dict(prior_ceiling=h, gross=e["gross"], binding=e["binding"],
                        delta=e["haircut_vs_prior"]))
    return out


def purchaser_diligence(p: Parcel) -> list:
    """
    What a PURCHASER inherits that a pre-fire owner never had to think about.

    The rebuild relief goes with the land — Malibu's own rebuild FAQ says the
    in-kind rebuild rights "go with the land" and a new owner can use the
    expedited processes and CDP exemptions provided the deadlines are met. The
    legislative record confirms it: SB 1229 (Allen) WOULD limit the CDP exemption
    to the owner of record immediately preceding the disaster — you cannot close a
    loophole that does not exist. Allen has said it is prospective and would not
    apply to the 2025 fires. Track it to the Assembly floor anyway.

    But three things attach to the PROPERTY and land on the buyer, and none are in
    the parcel record. They are diligence items, not model inputs.
    """
    flags = []

    flags.append(
        "<b>FEE-WAIVER COVENANT — check before offer.</b> Malibu's fee waiver is "
        "person-based: it requires the property to have been the owner's primary "
        "residence at the fire date, proven by notarised affidavit, and a covenant is "
        "recorded against the property. <b>If the property sells before Certificate of "
        "Occupancy, waived fees must be reimbursed within 90 days and development is "
        "halted until they are.</b> If a seller took the waiver and you buy pre-CO, you "
        "acquire a recorded covenant with a live reimbursement obligation and a stop-work "
        "trigger. Confirm whether the seller waived, whether an affidavit is recorded, and "
        "who pays.")

    flags.append(
        "<b>TEMPORARY HOUSING HISTORY — penalty attaches to the property.</b> Ordinance "
        "524 restricts temporary housing to fire-date occupants. Violation removes the "
        "structures, bars the property from temporary housing for <b>five years</b>, and "
        "carries $1,000/day fines with possible liens <b>on the property</b>. Check any "
        "lot where a seller placed a trailer.")

    flags.append(
        "<b>BUY THE EVIDENCE WITH THE DIRT.</b> Bulk is the binding constraint and it is "
        "total interior cubic volume of a building that no longer exists. A pre-fire owner "
        "has plans, photos, insurance measurements, memory. A purchaser has the Assessor "
        "and aerials. Issue No. 12 hard-requires a survey at Planning Verification. Make "
        "delivery of plans, surveys, insurance measurements, photos, prior CDPs and "
        "contractor files a condition of the PSA. This is the most underrated diligence "
        "item on the list.")

    flags.append(
        "<b>THE CLOCK RUNS FROM THE FIRE, NOT FROM ACQUISITION.</b> Palisades Fire "
        "7 Jan 2025 → planning application by <b>Jan 2031</b>, building permit by "
        "<b>Jan 2033</b>. Extensions from the Planning Commission on an undue-hardship "
        "finding cap at 2034 / 2036. A purchaser inherits the remaining clock, not a fresh "
        "one — which is exactly what a property-attached right looks like. Confirm no prior "
        "application has been filed and abandoned in a way that complicates the record.")

    if p.n_structures and p.n_structures > 1:
        flags.append(
            "<b>ISSUE No. 7 IS AIMED AT THIS.</b> The stated rationale is avoiding "
            "<i>\"consolidation of dispersed structures into a larger home that could have "
            "impacts on views or other sensitive resources.\"</i> Structures combine only "
            "if ≤10ft apart, use must be maintained, and uninhabitable square footage (a "
            "garage) must stay uninhabitable. It is the policy most likely to be applied "
            "firmly against a developer assembling square footage. <b>Lot assembly gets you "
            "nothing either</b> — relief is per-structure, per-pad, sited substantially in "
            "the same location. Two adjacent razed lots give you two like-for-like "
            "envelopes, not one merged one.")

    return flags


def the_record_exists() -> str:
    """
    THE CORRECTION THAT MATTERS MOST TO THIS TOOL.

    Every version of this file has said some form of "Malibu has issued ~22 permits,
    so there is no denominator, so no honest grant rate exists, so don't ask."

    That is right about RATES and wrong about EVIDENCE, and the difference is just
    labour.

    22 is unscoreable as a sample and completely readable as a CENSUS. You don't
    estimate from 22 files. You read all 22.

    Nobody has done this because Malibu's post-fire record is fourteen months old and
    the people who would normally have done it — the brokers, the land bankers — are
    moving faster than the analysis. That is an information advantage sitting on a
    public records portal.
    """
    return (
        "<b>The tool can't give you a grant rate. The record can give you something "
        "better.</b><br><br>"
        "Malibu has acted on roughly two dozen planning verifications since January 2025. "
        "That is unscoreable as a sample and <b>completely readable as a census</b>. You don't "
        "estimate from 22 files — you read all 22.<br><br>"
        "<b>The PRA request (cheap, and nobody has run it):</b> every planning verification "
        "acted on since January 2025. For each — was the +10% requested? Granted? In full or "
        "trimmed? Was the applicant a natural person or an entity? Was the property "
        "owner-occupied at the fire date? Was anything conditioned that the code doesn't "
        "require?<br><br>"
        "<b>Ask for the DENIALS and the WITHDRAWALS, not just the approvals.</b> A discretion "
        "that has never been exercised adversely and a discretion that gets exercised at the "
        "counter — applicant reads the room, trims the ask, never files — <b>look identical in "
        "a stack of approvals</b>. The withdrawn and revised applications are where the signal "
        "is, and they're the records nobody requests.<br><br>"
        "That won't produce a rate. It answers the question you're actually asking, which "
        "isn't <i>what's the probability</i> but <b>has the Planning Director ever exercised "
        "that discretion against anyone, and on what facts?</b> If all 22 got the 10% "
        "administratively, LLCs included, you don't have a rate — you have the complete "
        "history of the discretion being exercised, and it has never been exercised adversely. "
        "That is a defensible IC position. If it has, you'll know exactly what the trigger was, "
        "which is worth more than any percentage.<br><br>"
        "<b>Same structure for the access dedication.</b> Disaster rebuilds are a thin record, "
        "but Malibu beachfront new-development CDPs are decades of searchable staff reports at "
        "documents.coastal.ca.gov. How often did a lateral access condition attach? On what "
        "facts? What was the seaward expansion where it did? That's not a probability anyone "
        "hands you — it's a record you build in a week, and it's the only thing that tells you "
        "whether <i>your</i> massing sits in the exaction zone or outside it.<br><br>"
        "<span class='cite'>Why nobody's done it: the record is fourteen months old and the "
        "brokers and land bankers are moving faster than the analysis. That's an information "
        "advantage sitting on a public records portal.</span>")


def design_out_of_it() -> str:
    """
    THE DISCIPLINE WHEN THERE IS NO BASE RATE.

    Even after reading all 22, you won't have a probability. You'll have a census of
    n=22 and a decade of adjacent CCC precedent, and you'll still be extrapolating.

    So the IC question changes shape. It stops being "what's the probability" and
    becomes "can the fund survive being wrong, and what does it cost to not need the
    answer?"

    Not better estimation. Structures that don't require the estimate.
    """
    return (
        "<b>The discipline when there's no base rate isn't better estimation. It's "
        "structures that don't need the estimate.</b><br><br>"
        "&bull; <b>The +10%</b> — base case at 100%. On 1,650 sf the discretionary grant is "
        "165 sf. If 165 sf decides your deal, the deal is the problem. Don't buy the "
        "question.<br>"
        "&bull; <b>The access dedication</b> — don't estimate it, <b>design out of it</b>. The "
        "exaction risk is a property of your <i>massing</i>, not of the pathway. Expand "
        "landward and vertically within stringline and the Nollan nexus thins to nothing; "
        "widen along the beach and you hand the Commission the fit that Nollan itself "
        "lacked. That's a site plan and a coastal engineer, answerable now, and it tells you "
        "more than any probability.<br>"
        "&bull; <b>An unscoreable lot</b> — option it, don't buy it. Or make the bid "
        "contingent on establishing a baseline. Days and low four figures against the cost of "
        "buying raw beachfront at rebuild-rights pricing.<br>"
        "&bull; <b>PF1</b> — if a lot's thesis <i>is</i> the deemed-complete application, "
        "you're buying a legal opinion, not dirt. Structure the value into a price adjustment "
        "rather than your basis.<br><br>"
        "<span class='cite'>Three memos in, the questions being asked hardest — the grant "
        "rate, the dedication probability — are the two where no honest answer exists. The "
        "ones that do have answers, and would actually move an IC, are phone calls and a title "
        "search: prior height conformity on the beachfront lots, structure separations at "
        "20314, whether any seller had a live application on January 6. Nobody has run "
        "them.</span>")


def vacancy_diagnostic(p: Parcel) -> str:
    """
    THE DIAGNOSTIC IS IMPROVEMENT VALUE, NOT SQUARE FOOTAGE.

    We already pull Roll_ImpValue. It was sitting unused while the tool drew
    conclusions from a null square-footage field. Improvement value on the roll
    means the Assessor taxed a building. A null sf field alongside it is a records
    gap. Land value with zero improvement across years is the real signal.
    """
    iv = p.imp_value
    lv = p.land_value
    if iv is None and lv is None:
        return ("<span class='cite'>Roll values not returned — can't run the improvement-value "
                "diagnostic. Pull the tax roll history directly.</span>")
    if iv and iv > 0:
        return (f"<b>Improvement value on the roll: ${iv:,}.</b> The Assessor was taxing a "
                f"building. A null square-footage field alongside a live improvement value is "
                f"a <b>records gap</b>, not a vacancy — the structure existed and the "
                f"measurement is missing. This is the recoverable case. Run the archaeology.")
    if lv and (iv == 0 or iv is None):
        return (f"<b>Land value ${lv:,}, improvement value ${iv if iv is not None else 0:,}.</b> "
                f"Land-only with zero improvement is <b>the real signal</b> — but check it "
                f"across multiple roll years before concluding, and check it against CAL FIRE "
                f"DINS, which recorded what physically stood on 7 Jan. If genuinely vacant, "
                f"there is no baseline: no like-for-like, no +10%, no CDP exemption. Raw land, "
                f"full CDP. <b>Reprice or walk.</b>")
    return "<span class='cite'>Roll values inconclusive. Pull the tax roll history directly.</span>"


def no_prior_sqft_note(p: Parcel) -> str:
    """
    Issue No. 4 — WHAT AN EMPTY SQUARE-FOOTAGE FIELD ACTUALLY MEANS.

    An earlier version of this tool said: "If the Assessor listed the parcel as
    vacant BEFORE the fire, any structure on it is deemed illegal." That was wrong
    twice over and it pointed at the wrong risk.

    WRONG #1 — an empty field is not a vacancy finding. Absence of data is not an
    affirmative characterisation. A parcel can carry improvement value, a
    homeowner's exemption and decades of assessment history while the sf field is
    null: data migration, a base-year record predating digitisation, an improvement
    never re-measured. THE DIAGNOSTIC IS IMPROVEMENT VALUE, NOT SQUARE FOOTAGE.
    Land value + improvement value with a null sf field is a records gap. Land only,
    zero improvement across multiple years, is a real signal. Those two findings
    should drive completely different decisions.

    WRONG #2 — Issue No. 4 governs whether a structure that EXISTED was LAWFULLY
    ERECTED. If a lot was genuinely vacant, Issue No. 4 never engages, because there
    is no structure to characterise. And that outcome is MUCH WORSE than "deemed
    illegal," not better. An illegal structure is something you can argue about —
    bring aerials, CCC files, the Palisades relaxation. A vacant lot leaves no
    baseline, no like-for-like, no +10%, no CDP exemption. It is raw land requiring
    a full CDP for new development — which on beachfront drops you into the
    hazard / SLR / stringline / access-dedication analysis on a lot bought precisely
    for rebuild rights you don't have.

    The Assessor is ONE item on a non-exhaustive list. Issue No. 4: "Evidence that
    may be used to demonstrate the above includes, BUT IS NOT LIMITED TO, aerial and
    GIS imagery, photography, city records, Los Angeles County Assessor data, and
    California Coastal Commission records." An empty Assessor record is the failure
    of one of five named evidence types. It is not a determination.
    """
    return (
        "<b>No prior square footage in the Assessor record. That is a blank cell, not a "
        "finding.</b><br><br>"
        + vacancy_diagnostic(p) + "<br><br>"
        "Three different worlds, and the tool cannot tell them apart:<br>"
        "&bull; <b>Records gap, structure existed</b> — most likely. Recoverable through "
        "archaeology.<br>"
        "&bull; <b>Structure existed but wholly unpermitted</b> — Issue No. 4 engages, and "
        "for Palisades the test is generous (below).<br>"
        "&bull; <b>Genuinely vacant</b> — no baseline, no like-for-like, no +10%, no CDP "
        "exemption. Raw land needing a full CDP. <b>This is the bad one</b>, and on "
        "beachfront it means buying into the hazard/SLR/stringline/access analysis on a lot "
        "priced for rebuild rights you don't have.<br><br>"
        "<b>The diagnostic is IMPROVEMENT VALUE, not square footage.</b> Pull the tax roll "
        "history. Land value <i>and</i> improvement value with a null sf field is a records "
        "gap. Land only, zero improvement across multiple years, is a real signal.<br><br>"
        "<b>Where to look — the Assessor is the WORST of the available sources:</b><br>"
        "&bull; <b>CAL FIRE DINS</b> ('DINS 2025 Palisades Public View') — state-agency, "
        "contemporaneous, parcel-level record of what physically stood on 7 Jan, with APN "
        "appended and photos often available. Free. Presence is proof of presence; absence "
        "isn't proof of absence.<br>"
        "&bull; <b>Debris removal records</b> — if something was hauled, someone measured and "
        "logged it.<br>"
        "&bull; <b>Coastal Commission files</b> — named in Issue No. 4. Any post-1976 CDP is "
        "in Ventura district files, and CDP applications carry dimensioned plans.<br>"
        "&bull; <b>LA County permits, pre-1991.</b> Malibu incorporated in 1991. An older "
        "house's permit was never Malibu's to lose — it's the County's. Searching only "
        "MalibuCity.org means searching the wrong archive.<br>"
        "&bull; <b>Historical aerials</b> (UCSB's California coast collection goes back to "
        "the 1920s) — this is how you prove pre-1976 existence on a beachfront parcel.<br>"
        "&bull; <b>MLS history</b> — if it ever traded, the listing carried a square footage, "
        "often predating the Assessor's digital record.<br>"
        "&bull; <b>The seller's insurance file</b> — the carrier ran a replacement-cost "
        "estimate with square footage, and there's a post-fire claim file. Sellers hand these "
        "over without thinking about what they're worth to you.<br><br>"
        "<b>If the structure was unpermitted, the Palisades relaxation does heavy lifting.</b> "
        "For 2025 Palisades Fire structures only, 'lawfully erected' also includes any "
        "structure that physically existed immediately prior to the fire, provided it wasn't "
        "subject to an open code enforcement violation, didn't violate a law beyond the City's "
        "power to waive, and <i>\"has a building permit that allows the structure to exist in "
        "some form\"</i> — with the gloss that an unpermitted remodel or addition "
        "<i>\"would not disqualify the whole structure.\"</i> You need <i>a</i> permit letting "
        "it exist in <i>some</i> form. Not one matching what burned. That is a low bar, and it "
        "forgives the unpermitted-addition problem across 1950s-70s Malibu stock.<br><br>"
        "<b>Resolve beachfront status first — it moves the evidentiary target by 15 years.</b> "
        "The general test accepts evidence of existence prior to City incorporation (1991), "
        "<i>\"except structures located on a beach, coastal bluff, within an environmentally "
        "sensitive habitat area, or other sensitive coastal resource area must be shown to "
        "have existed prior to the California Coastal Act\"</i> (1976).<br><br>"
        "<span class='cite'><b>Don't score it. Structure it.</b> Make the bid contingent on "
        "establishing a baseline — a price adjustment or a short option while you run DINS, "
        "debris records, County permits and aerials. Days and low four figures, not weeks. The "
        "cost of being wrong is buying raw beachfront at rebuild-rights pricing, and there is "
        "no version of that you fix later.<br><br>"
        "This is the only lot in the set where you <b>know</b> you don't know — which makes it "
        "the only one you're priced correctly for. On the others you may be assuming a "
        "baseline you haven't verified either.</span>")


def baseline_provenance_warning(p: Parcel) -> str:
    """
    The line this tool most needed to hear: "the other six, you may be assuming a
    baseline you haven't verified either."

    The tool tags SQFTmain as SOURCED. That is true about where the number came
    from and misleading about what it establishes. The Assessor is a taxation body.
    It doesn't adjudicate permits, and Issue No. 4 lists it as one of five
    non-exhaustive evidence types. Issue No. 12 requires a SURVEY at Planning
    Verification precisely because the Assessor and the plans disagree.

    So: SOURCED, yes. VERIFIED BASELINE, no. Those are different claims and the tool
    should not blur them.
    """
    return (
        "<b>This baseline is Assessor data. That is a source, not a verified envelope.</b><br>"
        "The Assessor is a taxation body — it doesn't adjudicate permits, and Issue No. 4 "
        "names it as one of five non-exhaustive evidence types. Issue No. 12 hard-requires a "
        "<b>survey at Planning Verification</b> precisely because the Assessor and the plans "
        "disagree. Every envelope below inherits whatever error is in this one number.<br><br>"
        "<b>Two known ways it's wrong, both in your favour if you check:</b><br>"
        "&bull; <b>Basements.</b> Assessor square-footage conventions frequently exclude or "
        "inconsistently capture below-grade area. If a prior basement isn't in this figure, "
        "your baseline is <b>understated</b> — and prior basement volume sits in the envelope "
        "for free, multiplies by 1.10, and gets the first 1,000 sf discounted from TDSF under "
        "MMC 17.40.040(A)(13)(c), a discount Issue No. 5 confirms doesn't reach the 110%. "
        "<i>Verify the LA County convention rather than taking this on faith.</i><br>"
        "&bull; <b>A new basement is the worst possible use of the 10%</b> — it eats the whole "
        "allowance in bulk and returns zero height [Issues No. 1 and No. 5]. A <i>prior</i> "
        "basement is worth real money. Check the permit record.<br><br>"
        "<span class='cite'>The same archaeology that resolves an unscoreable lot resolves the "
        "basement question across the whole set. One workstream, not two, with upside on both "
        "ends.</span>")


def tdsf_cap(lot_sqft: Optional[float], is_beachfront: Optional[bool]) -> Optional[dict]:
    """
    MMC 17.40.040(A)(13) — Total Development Square Footage.

    *** BEACHFRONT LOTS ARE EXEMPT FROM THIS SUBSECTION ENTIRELY. ***

    That exemption is the plain text of the code, and it matters: on a beachfront
    lot, TDSF is not a constraint at all, so the rebuild envelope plus an ADU is
    limited by Interpretation No. 24 and nothing else.

    On NON-beachfront lots the sliding scale binds:
        TDSF = 17.7% of lot area + 1,000 sf   (lots up to 1/2 acre)
        floor: lots of 5,000 sf or less are capped at 1,885 sf

    Note the two-meter problem [Issue No. 5]: MMC 17.40.040(A)(13)(c) discounts the
    first 1,000 sf of basement toward TDSF, but that discount does NOT carry over to
    the 110% calculation. A basement can be TDSF-favoured and still consume the
    rebuild envelope in full. Two different meters, and they don't talk.

    An ADU over 800 sf counts toward TDSF where TDSF applies. On beachfront it
    doesn't matter. Off beachfront it can bind before the rebuild rule does.
    """
    if is_beachfront is True:
        return dict(applies=False,
                    note=("<b>Beachfront — exempt from TDSF.</b> MMC 17.40.040(A)(13) "
                          "exempts beachfront lots from the total-development-square-footage "
                          "cap by its own terms. The rebuild envelope plus an ADU is limited "
                          "by Interpretation No. 24 and nothing else here."))
    if not lot_sqft:
        return dict(applies=None,
                    note=("<b>TDSF status unknown.</b> Lot size not returned by the county "
                          "layer, and beachfront status not supplied. Off beachfront the cap "
                          "is 17.7% of lot area + 1,000 sf (min 1,885 on lots ≤5,000 sf) and "
                          "can bind before the rebuild rule does."))
    cap = 1885 if lot_sqft <= 5000 else round(0.177 * lot_sqft + 1000)
    return dict(applies=True, cap=cap,
                note=(f"<b>TDSF cap ≈ {cap:,} sf</b> (17.7% of {lot_sqft:,.0f} sf + 1,000; "
                      f"floor of 1,885 on lots ≤5,000 sf). Non-beachfront lots are subject to "
                      f"this. An ADU over 800 sf counts toward it. Check the rebuild envelope "
                      f"plus any ADU against this number — TDSF can bind before Interpretation "
                      f"No. 24 does."))


def beachfront_fork(is_beachfront: Optional[bool]) -> str:
    """
    Beachfront status is the single most load-bearing parcel fact in this tool, and
    it cuts in OPPOSITE directions. It is not one flag; it is a fork.

    It is not in the county record. It is determinable from the City's GIS layers or
    by standing on the lot.
    """
    if is_beachfront is None:
        return ("<b>Beachfront or not? This is the fork, and it isn't in the county "
                "record.</b><br>"
                "It cuts both ways, so 'unknown' is not a small gap:<br><br>"
                "<b>Beachfront</b> — exempt from TDSF [MMC 17.40.040(A)(13)]. No Site Plan "
                "Review under Issue No. 9. Height measured from the wave-action finish floor, "
                "not grade. Setbacks by stringline. Seawall available through a "
                "director-level rebuild permit. <i>But</i> exceeding the 10% cap triggers the "
                "PRC 30212 public-access cliff, and armoring policy flips against you.<br><br>"
                "<b>Non-beachfront</b> — TDSF binds (17.7% of lot + 1,000). Shifted bulk above "
                "18ft outside the original envelope needs SPR. No access cliff.<br><br>"
                "<span class='cite'>Determinable from the City's GIS layers, or by standing on "
                "the lot. Free. <b>Do it before anything else</b> — and not just because it "
                "forks the envelope. It also sets the evidentiary target for Issue No. 4 by "
                "fifteen years: the general test accepts proof of existence prior to City "
                "incorporation (1991), <i>except</i> structures on a beach, coastal bluff, in "
                "ESHA or other sensitive coastal resource area, which must be shown to have "
                "existed prior to the Coastal Act (1976). Resolve beachfront first or you'll "
                "send someone to the wrong decade of aerials.</span>")
    if is_beachfront:
        return ("<span class='cite'><b>Beachfront.</b> Exempt from TDSF. No SPR under Issue "
                "No. 9. Height from the wave-action finish floor. Stringline setbacks. Seawall "
                "via director-level rebuild permit — <i>so long as you stay inside the 10% "
                "cap</i>.</span>")
    return ("<span class='cite'><b>Non-beachfront.</b> TDSF binds. Shifted bulk above 18ft "
            "outside the original envelope triggers SPR [Issue No. 9] — take the allowance "
            "laterally and inside the envelope to avoid it. No PRC 30212 access cliff "
            "here.</span>")


def thesis_fit(prior_sqft: Optional[int], is_beachfront: Optional[bool] = None) -> str:
    """
    Score the lot against the thesis Tal actually landed on in the 20 July meeting,
    which is NOT the thesis the tool was built for.

    His words: "it's better for us to find properties that had a big house before,
    that we can build the same size, perhaps with 10% but that 10% will be bonus,
    not guaranteed."

    So the screen inverts. The old tool asked "how much can I add?" This asks "what
    burned here, and was it already big enough to be the product?" A lot whose prior
    house was already ~2,700+ sf lets you rebuild the product like-for-like — no
    discretionary grant, no CDP, no fight. A lot whose prior house was 900 sf can
    only reach the product through exactly the entitlement risk he wants to avoid.

    Under this thesis the value of a burn lot is what burned on it. A big recent
    house on a buildable lot is the asset. The rebuild rule is a floor you're
    standing on, not a ceiling you're fighting.
    """
    if not prior_sqft:
        return ("<span class='cite'>No prior square footage, so thesis fit can't be scored — "
                "resolve the baseline first. A lot with no prior structure only fits the "
                "thesis if it arrives with approved plans (set entitlement status above).</span>")
    lf = prior_sqft
    lf10 = round(prior_sqft * 1.10)
    if prior_sqft >= 2500:
        tier = ("<b>STRONG THESIS FIT.</b> Prior house was already large. You rebuild the "
                "product like-for-like — no discretionary +10%, no CDP, no fight. This is "
                "exactly the lot the strategy calls for: what burned here IS the product.")
        color = "#1f5c2e"
    elif prior_sqft >= 1800:
        tier = ("<b>MODERATE FIT.</b> Prior house was mid-sized. Like-for-like gets you a "
                "reasonable home; the +10% helps but isn't the difference between viable and "
                "not. Workable without entitlement risk.")
        color = "#8a5a00"
    else:
        tier = ("<b>WEAK FIT for the like-for-like thesis.</b> Prior house was small. "
                "Reaching a beachfront-comp product means exceeding the envelope — which is "
                "the discretionary grant, the CDP, and (on beachfront) the access cliff. This "
                "lot only works as a small-house play, or if it carries approved plans.")
        color = "#7a2518"
    return (f"<b style='color:{color}'>{tier}</b><br>"
            f"<span class='cite'>Rebuild like-for-like: <b>{lf:,} sf</b>. With the discretionary "
            f"+10% if granted: {lf10:,} sf. Under the thesis, model the {lf:,} and treat the "
            f"grant as bonus.</span>")


def entitlement_status(has_plans: str, plan_sqft: Optional[int] = None,
                       is_beachfront: Optional[bool] = None) -> Optional[dict]:
    """
    THE CONSTRAINT ISN'T ALWAYS THE REBUILD RULE.

    Two lots defeated the screener because it assumed the binding constraint was
    always Interpretation No. 24 / EO1. It isn't. A lot can arrive already entitled,
    and then the plans ARE the envelope — the rebuild math is moot.

    This maps onto the thesis Tal landed on: find lots that are easy to build big,
    treat the +10% as bonus not basis. An approved-plans lot is the purest version
    of that — zero entitlement risk, start tomorrow. The tool should rank those at
    the TOP, not choke on them for lacking a prior square footage.

    Three states, in descending order of how much they de-risk the deal:

      APPROVED  — plans approved, ready to issue, or permits pulled. The envelope is
                  whatever was approved. Rebuild math irrelevant. Best possible
                  status: buy the entitlement, not the argument.
      IN_PROCESS — an application on file. PF1 territory if it predates the fire.
                  Real option value, not yet certain.
      NONE      — no entitlement. The rebuild rule governs; the rest of the tool
                  applies normally.
    """
    if has_plans == "APPROVED":
        lines = [
            "<b>ALREADY ENTITLED — the plans are the envelope. The rebuild math below "
            "doesn't govern.</b>",
        ]
        if plan_sqft:
            lines.append(f"Approved for <b>{plan_sqft:,} sf</b>. That number isn't subject to "
                         f"the +10% ceiling, the volume cap, or a discretionary grant — it's "
                         f"approved.")
        lines += [
            "The strongest status a lot can have, and it maps to the thesis directly: buy lots "
            "that are easy to build big, and an approved-plans lot has <b>zero entitlement "
            "risk</b>. You start tomorrow.",
            "",
            "<span class='cite'><b>Verify the plans are real, current, and transferable:</b> "
            "pull the stamped set and the permit / Ready-to-Issue status from the jurisdiction "
            "(LADBS for City of LA, Malibu Planning for Malibu). Approved plans generally run "
            "with the property, but an RTI status can lapse and permits have their own clocks. "
            "Make delivery of the stamped set a PSA condition. If the thesis of the lot IS the "
            "plans, you're buying an entitlement — price it there, not in the dirt.</span>",
        ]
        return dict(status="APPROVED", ranks_top=True, note="<br>".join(lines))

    if has_plans == "IN_PROCESS":
        return dict(status="IN_PROCESS", ranks_top=False, note=(
            "<b>Application on file — real option value, not yet certain.</b> If it was "
            "deemed complete before the fire, this is PF1 territory: the owner may build both "
            "the replacement and the pending application, combined and treated as like-for-"
            "like. Confirm the status and the date, and whether it transfers to a purchaser "
            "(unresolved — ask Community Development via a neutral hypothetical, not in the "
            "fund's name). Structure the value into a price adjustment, not your basis."))

    return None


def realistic_program(prior_sqft: float, prior_ceiling: float, proposed_ceiling: float,
                      basement_sqft: float = 0.0, lot_sqft: Optional[float] = None,
                      is_beachfront: Optional[bool] = None):
    """
    What you can actually build without a CDP — the honest ceiling.

    The exemption envelope is not the whole story. Legitimate additions on top:

      ADU up to 1,000 sf (Ordinance 524's cap), with the garage (400 sf max) and
      attached exterior decks/overhangs EXCLUDED from that limit. AB 462 (urgency
      statute, 10 Oct 2025) eliminated Coastal Commission appeal authority over
      local CDPs for ADUs and imposed a 60-day local clock. SB 1077 required the
      Commission and HCD to publish coastal-zone ADU streamlining guidance by
      1 July 2026 — that date has passed; check what actually issued.

      The ADU does not consume the 110%. On beachfront it doesn't hit TDSF either,
      because beachfront is TDSF-exempt. Off beachfront, an ADU over 800 sf counts
      toward TDSF and can bind before the rebuild rule.

    Also real but small: Issue No. PF3 (Palisades, beachfront) — interior access
    stairs required by code because of the new FEMA finished-floor don't count
    toward the 10%. A free staircase.

    THE HONEST CONCLUSION
    On a 1,760 sf prior: ~1,936 sf primary + up to ~1,000 sf ADU = ~2,900 sf across
    TWO units, one an accessory unit with its own kitchen and entry.

    That is a well-located small house with a guest unit. It is not the thing that
    trades against Malibu beachfront comps. If the model needs a single integrated
    2,700+ sf luxury envelope, the exemption path does not produce it — and there is
    no intermediate instrument. The DMWs in Ordinance 524 cover FEMA finished-floor
    elevation, relocation, seawalls, OWTS and water tanks. None of them grants floor
    area. The rebuild development permit covers shoring, OWTS, seawalls, driveways
    and works necessary to construct the replacement structure. Not more house.
    """
    both = envelope_both_cases(prior_sqft, prior_ceiling, proposed_ceiling, basement_sqft)
    primary_aor = both["as_of_right"]["habitable"]
    primary_ifg = both["if_granted"]["habitable"]
    adu_max = 1000
    t = tdsf_cap(lot_sqft, is_beachfront)
    total_ifg = primary_ifg + adu_max
    tdsf_binds = bool(t and t.get("applies") and t.get("cap") and total_ifg > t["cap"])
    return dict(
        primary_as_of_right=primary_aor,
        primary_if_granted=primary_ifg,
        adu_max=adu_max,
        garage_free=400,
        total_as_of_right=primary_aor + adu_max,
        total_if_granted=total_ifg,
        tdsf=t,
        tdsf_binds=tdsf_binds,
        note=("Two units, not one integrated envelope. The ADU has its own kitchen and "
              "entry and does not consume the 110%."),
    )


def access_dedication_warning(is_beachfront: Optional[bool],
                              exceeds_10pct: bool) -> Optional[str]:
    """
    THE CLIFF. Breaking the 10% cap on beachfront may cost a permanent public
    access dedication — not just time.

    The LIP's "New Development" exclusion is CONDITIONAL, and the 10% cap is the
    condition:

      "For purposes of implementing the public access requirements of Public
       Resources Code Section 30212 ... 'new development' includes 'development' ...
       except for the following: a. Structures destroyed by natural disaster: The
       replacement of any structure ... PROVIDED THAT the replacement structure
       conforms to applicable existing zoning requirements, is for the same use ...
       DOES NOT EXCEED either the floor area, height, or bulk of the destroyed
       structure BY MORE THAN 10%, is sited in the same location ... and does not
       extend the replacement structure seaward on a sandy beach or beach fronting
       bluff lot."

    Break the cap and you are not merely losing a shortcut. You become "new
    development" for public access purposes, and PRC 30212(a) requires that public
    access from the nearest public roadway to the shoreline be provided in new
    development projects.

    The Commission has applied exactly this in Malibu. 2011 appeal, staff analysis:
    the 30212(b) exceptions didn't apply because "the project is not the replacement
    of a structure destroyed in a disaster... the demolition of the existing
    single-family residence and reconstruction of the proposed home will increase
    the floor area by more than 10 percent as compared to the existing home...
    Therefore, the City was correct by processing this application as a new
    development."

    SECOND CASCADE — ARMORING. The LCP requires new development on the beach or
    oceanfront bluff to be set back as far as possible and elevated above base flood
    elevation, and provides that new development requiring shoreline armoring
    SHOULD BE PROHIBITED. Meanwhile Ordinance 524 gives REPLACEMENT structures a
    director-level rebuild permit path for new seawalls protecting an OWTS. That
    asymmetry is enormous on beachfront. Replacement structure: seawall via
    director. New development: armoring policy runs against you.

    THIRD — SEA LEVEL RISE. Under current Commission guidance, properties in
    projected 75-year inundation zones face enhanced setback, hardening and
    removability requirements; some Malibu and Manhattan Beach projects have been
    conditioned with adaptive-use clauses and conditional removal triggers. A
    conditional-removal covenant on a beachfront spec product is a financing and
    exit problem, not a design detail.

    So the correct framing is NOT "small house quickly or large house slowly." On
    beachfront it is: "large house, maybe, with conditions that may destroy the
    reason you wanted it large."
    """
    if not exceeds_10pct:
        return None
    if is_beachfront:
        return ("<b>STOP — exceeding the 10% on beachfront may cost a public access "
                "dedication.</b><br>"
                "The LIP's 'New Development' exclusion is <b>conditional</b>, and the 10% cap "
                "is the condition. Break it and you become 'new development' for public "
                "access purposes — and PRC 30212(a) requires public access from the nearest "
                "public roadway to the shoreline in new development projects.<br><br>"
                "<b>The Commission has applied this in Malibu.</b> A 2011 appeal: the "
                "exceptions didn't apply because the project wasn't a disaster replacement "
                "and increased floor area by more than 10% — <i>'Therefore, the City was "
                "correct by processing this application as a new development.'</i><br><br>"
                "That is a permanent recorded encumbrance that hits the exit comp directly. "
                "<b>No amount of patience solves it.</b><br><br>"
                "<b>Armoring flips too.</b> Replacement structures get a seawall through a "
                "director-level rebuild permit (Ordinance 524). New development runs into the "
                "LCP policy that development requiring shoreline armoring should be "
                "<i>prohibited</i>.<br><br>"
                "<b>And sea level rise.</b> Properties in projected 75-year inundation zones "
                "face enhanced setback, hardening and removability conditions. Some Malibu "
                "projects have been conditioned with adaptive-use clauses and conditional "
                "removal triggers. A conditional-removal covenant on a beachfront spec "
                "product is a financing and exit problem, not a design detail.<br><br>"
                "<span class='cite'>The framing isn't 'small house quickly or large house "
                "slowly.' On beachfront it's 'large house, maybe, with conditions that may "
                "destroy the reason you wanted it large.'</span>")
    return ("<b>Exceeding the 10% forfeits the exemption.</b> You leave Interpretation No. 24 "
            "entirely and enter the ordinary LCP: full CDP, hazard chapter, TDSF limits. The "
            "beachfront access-dedication cascade under PRC 30212 doesn't apply here, but the "
            "timeline does — Malibu's published 12-24 months is a floor, not a range.")


def spr_check(is_beachfront: Optional[bool], proposed_ceiling: float,
              storeys_proposed: int = 1, prior_height_ft: Optional[float] = None,
              spend_allowance_vertically: bool = False) -> Optional[str]:
    """
    Interpretation No. 24, Issue No. 9 — SPR IS TRIGGERED BY THE *INCREASE*,
    NOT BY THE STRUCTURE'S HEIGHT.

    Earlier versions of this function got this wrong and flagged SPR on any
    non-beachfront lot whose total height cleared 18ft. That is not what the
    ordinance says.

    Issue No. 9: "increases to height or bulk above 18 feet shall require a site
    plan review (SPR) on non-beachfront properties."
    Ordinance 524: "Increased height or bulk on non-beachfront properties shall not
    exceed 18 feet, unless a site plan review is obtained."

    The subject of both sentences is the INCREASE. Rebuild a 24ft Las Flores house
    at 24ft and nothing is increased — no SPR on height. You only hit SPR when you
    spend the +10% VERTICALLY past 18ft, or when (per Issue No. 1) bulk is shifted
    to other parts of the structure and that bulk exceeds 18ft in height AND sits
    outside the original building envelope.

    THE DESIGN INSTRUCTION THAT FOLLOWS
    Take the 10% laterally. Keep the roofline at prior height. Stay inside the
    original envelope. That avoids SPR entirely. And since the allowance is
    bulk-constrained anyway — you generally cannot have both height and area —
    spending it horizontally is close to free.

    If SPR IS needed it is director-level, not a Planning Commission hearing. But
    it notices property owners within 500ft (no fewer than 10 developed
    properties), and 1,000ft in RR-10/RR-20 zones. Ordinance 524 added
    MMC 17.62.040(A)(13) covering non-beachfront development over 18ft on
    RELOCATED replacement structures — with 1,000ft noticing. Move the structure
    and the radius quintuples along with your comment exposure.

    The standard is "substantial evidence supports the findings" after consultation
    with six specialists. Not a rubber stamp. In a city that has issued roughly two
    dozen permits in a year, "routine" is not a word to lean on.

    UNVERIFIED: whether SPR decisions are appealable to the Planning Commission and
    then Council under Malibu's code. That materially changes tail risk. Ask counsel.
    """
    if is_beachfront is None:
        return ("<b>SPR status unknown — beachfront or not?</b> Not in the county record. "
                "On NON-beachfront lots, spending the +10% vertically past 18ft triggers "
                "Site Plan Review [Issue No. 9]. Determinable per parcel from the City's "
                "GIS layers. Note the trigger is the <i>increase</i>, not the structure — "
                "rebuild at prior height and no SPR is triggered on height.")
    if is_beachfront:
        return None

    if not spend_allowance_vertically:
        return ("<span class='cite'><b>No SPR triggered on height.</b> Non-beachfront, and "
                "you're taking the allowance laterally at prior roofline. The trigger is the "
                "<i>increase</i> above 18ft, not the structure's height — rebuild a 24ft "
                "house at 24ft and nothing is increased [Issue No. 9]. Bulk shifted outside "
                "the original envelope above 18ft would still trigger it [Issue No. 1]. "
                "Setback encroachments trigger review separately.</span>")

    return ("<b>SITE PLAN REVIEW REQUIRED [Issue No. 9].</b> Non-beachfront, and you're "
            "spending the +10% vertically past 18ft.<br><br>"
            "<b>The appeal SUSPENDS the approval. That's the whole problem.</b><br>"
            "MMC 17.62.040(E) routes to 17.04.220: any aggrieved person appeals the Director "
            "to the <b>Planning Commission</b>, and from there to <b>City Council</b>. Both "
            "rungs confirmed. And: <i>\"An action of the planning manager/director appealed to "
            "the planning commission shall not become effective unless and until final action "
            "by the planning commission.\"</i><br><br>"
            "Not enjoined — <b>suspended by operation of the code</b>. Any neighbour who "
            "dislikes your story poles suspends your approval by filing a form. Their cost is "
            "a filing fee. That is a free option written to every adjacent owner.<br><br>"
            "<b>And the findings are view findings, so the neighbours decide.</b> "
            "MMC 17.62.040(D) requires that the project <i>\"does not obstruct visually "
            "impressive scenes of the Pacific Ocean... from the main viewing area of any "
            "affected principal residence.\"</i> Combined with 500ft noticing (1,000ft if you "
            "also relocate), an SPR is functionally a neighbour referendum on your "
            "roofline.<br><br>"
            "<b>Story poles.</b> MMC Chapter 17.42: where SPR is required, <i>\"the entire "
            "development above 18 feet, including all roof projections, requires the "
            "installation of story poles.\"</i> You erect a physical outline of your massing "
            "for the neighbourhood to look at before the decision. Nothing generates appeals "
            "like story poles. <span class='cite'>(Ch. 17.42 is Custom Development Criteria "
            "and may not reach every parcel — verify.)</span><br><br>"
            "<b>The 30-day clock is a trap.</b> The code says decide within 21-30 days of the "
            "notice of filing (60 with Environmental Review Board referral), then says: "
            "<i>\"These deadlines are directory and no decision shall be subject to "
            "invalidation solely on the ground that it was made after the deadline.\"</i> A "
            "clock the code tells you isn't enforceable.<br><br>"
            "<b>Two procedural crumbs:</b> only matters raised in the appeal get reviewed — no "
            "roving review. And an appellant who doesn't file specific grounds within 10 days "
            "gets their fee returned and the appeal is deemed withdrawn. Sloppy appellants "
            "self-destruct.<br><br>"
            "<b style='color:#7a2518'>You probably don't need any of this.</b> The allowance "
            "is bulk-constrained — you generally can't have both height and area. Take the 10% "
            "laterally, hold the prior roofline, stay inside the original envelope, and SPR "
            "goes away entirely. That isn't schedule optimisation. <b>It's declining to hand "
            "five neighbours a suspension switch.</b>")


def issue10_exposure() -> str:
    """
    THE EXPOSURE EVERYONE MODELS WRONG.

    Issue No. 10 doesn't need to be struck down. It needs to be DISREGARDED — and
    that requires no litigation, no finding, no adverse ruling.

    On appeal, after a substantial-issue finding, the Commission considers the
    application DE NOVO, and the test is whether the development conforms to the
    certified Local Coastal Program and the public access policies of the Coastal
    Act. Certified LCP. Not Interpretation No. 24. The Commission is not bound by,
    does not defer to, and has no obligation to even discuss the City's construction
    of certified text.

    In that room Issue No. 10 has to stand alone on two defects:
      SCOPE — the definition says "For purposes of implementing the public access
        requirements of PRC Section 30212 and of this Section." Issue No. 10 uses a
        public-access carve-out to decide a flood-hazard question in a different
        chapter.
      CIRCULARITY — the exclusion is conditioned on the replacement structure
        "conform[ing] to applicable existing zoning requirements." Issue No. 10 uses
        it to establish non-application of a zoning requirement.

    Reinforced by Malibu's own LIP 1.3: where the LCP and a City resolution conflict
    and both can't be met, "the LCP shall take precedence." And by the Commission's
    own certified text — LIP 13.4.11(A)(4) exists precisely to handle FEMA-driven
    finished floor through a WAIVER, which is the Commission's answer to the question
    Issue No. 10 says needs no answer.
    """
    return (
        "<b>Issue No. 10's risk isn't invalidation. It's that the Commission never has to "
        "accept it.</b><br><br>"
        "On appeal the Commission reviews <b>de novo</b> against the <b>certified LCP</b> and "
        "the Coastal Act's public access policies. Not Interpretation No. 24 — the Commission "
        "isn't bound by it, doesn't defer to it, and has no obligation to discuss it. So "
        "Issue No. 10 doesn't need to be struck down. It just isn't the governing document in "
        "the room. That requires no litigation, no finding, no adverse ruling.<br><br>"
        "<b>Where it bites, in order of likelihood:</b><br>"
        "1. <b>Nobody appeals; nothing happens.</b> Most likely. Exemptions are quiet.<br>"
        "2. <b>A DMW gets appealed</b> by an aggrieved person within 10 working days in the "
        "appeal jurisdiction — Commission reviews against certified text, Issue No. 10 is "
        "irrelevant, you argue the waiver on its merits.<br>"
        "3. <b>The Executive Director disputes the exemption determination.</b> The channel "
        "people forget. Doesn't need a neighbour or a lawsuit — needs a staff analyst deciding "
        "your file isn't exempt.<br>"
        "4. <b>A third party challenges the interpretation itself.</b> Surfrider is the "
        "obvious candidate; they're already on record about developers getting the same "
        "fast-tracking as a displaced family, and they'd want a clean vehicle.<br><br>"
        "<b>Timing is the whole risk profile.</b> None of this is front-loaded. The City "
        "issues your planning verification quickly and cheaply, and the exposure matures when "
        "you're vertical, or at CO, or — worst — <b>at your exit, when your buyer's counsel "
        "reads the file and finds a house built in reliance on an uncertified interpretation "
        "of a state-certified document.</b> That's not a permit problem. That's a "
        "marketability problem, and it doesn't appear anywhere in a construction "
        "schedule.<br><br>"
        "<b style='color:#7a2518'>The mitigation is cheap and nobody does it:</b> where the "
        "project can qualify under the <b>certified</b> LIP 13.4.11(A)(4) waiver, <b>take the "
        "waiver even though Issue No. 10 says you don't need it.</b> You're buying a certified "
        "instrument with Commission-facing findings instead of relying on an uncertified City "
        "memo. Costs a noticing period and a 10-day appeal window. Buys a clean file. On "
        "beachfront at these price points that trade is obviously correct.")


def nollan_reality() -> str:
    """
    Why "design out of it" is the entire strategy rather than risk mitigation.

    The legal analysis favours you and Nollan is nearly your facts: beachfront
    rebuild, small bungalow demolished, larger house proposed, Commission
    conditioned the permit on a lateral access easement. Struck for want of
    essential nexus. Dolan added rough proportionality. Sheetz (2024) confirmed
    Nollan/Dolan reach legislatively-imposed conditions, so the Commission can't
    launder an exaction through LCP policy.

    Nollan's defect was MISMATCH — the stated harm was visual blockage and a
    "psychological barrier," the remedy was lateral passage. The easement didn't fix
    the harm identified. Reverse it: articulate a burden on lateral passage and
    demand a lateral easement, and nexus exists.

    THE UNCOMFORTABLE PART: the Nollan defence is strong on the merits and close to
    worthless as a business matter. You need the permit; they don't need anything.
    The Commission's leverage isn't legal correctness — it's that vindicating your
    rights takes years you don't have, in front of a body you'll be back in front of.
    Nollan itself took a decade and went to the Supreme Court. Applicants concede
    these conditions not because they're valid but because conceding is faster.

    A constitutional defence you'd never actually assert has no value in your model.
    A massing that never triggers the demand has all of it.
    """
    return (
        "<b>Nollan is nearly your facts — and that's worth less than it sounds.</b><br><br>"
        "<i>Nollan</i> was a beachfront rebuild: bungalow demolished, larger house proposed, "
        "Commission conditioned the permit on a lateral access easement. Struck for want of "
        "essential nexus. <i>Dolan</i> added rough proportionality. <i>Sheetz</i> (2024) "
        "confirmed both reach legislatively-imposed conditions — the Commission can't launder "
        "an exaction through LCP policy.<br><br>"
        "<b>Nexus turns on your massing.</b> Nollan's defect was mismatch: the stated harm was "
        "visual blockage, the remedy was lateral passage. The easement didn't fix the harm "
        "identified. Reverse it — articulate a burden on lateral passage, demand a lateral "
        "easement — and nexus exists. So: <b>expand landward and vertically within stringline "
        "and the lateral-passage burden is unchanged, which leaves the nexus story nothing to "
        "attach to.</b> Widen along the beach and you hand them the fit Nollan lacked.<br><br>"
        "Two more things work for you: PRC 30212(a)'s own exceptions do independent work — "
        "notably <i>adequate access exists nearby</i>, live in eastern Malibu — and below mean "
        "high tide is already public trust, so an exaction can only reach dry sand. On a "
        "narrow lot there may be very little to grab.<br><br>"
        "<b style='color:#7a2518'>Now the uncomfortable part.</b> The Nollan defence is strong "
        "on the merits and close to worthless as a business matter. <b>You need the permit. "
        "They don't need anything.</b> The Commission's leverage isn't legal correctness — "
        "it's that vindicating your rights takes years you don't have, in front of a body "
        "you'll be back in front of. Nollan itself took a decade and went to the Supreme "
        "Court. Applicants concede these conditions not because they're valid but because "
        "conceding is faster.<br><br>"
        "<b>Which is why 'design out of it' isn't risk mitigation. It's the entire "
        "strategy.</b> A constitutional defence you'd never actually assert has no value in "
        "your model. A massing that never triggers the demand has all of it.")


def height_conformity_flag(prior_height_ft: Optional[float] = None,
                           conforming: Optional[bool] = None) -> str:
    """
    THE SINGLE DILIGENCE ITEM THAT COLLAPSES THE ISSUE No. 10 UNCERTAINTY.

    The certified DMW (LIP 13.4.11(A)(4)) is the safety net if Issue No. 10's
    reasoning is challenged — it waives FEMA-driven finished-floor increases. But
    it has a hard wall:

      "The height of the structure from the finished floor to the roof may remain
       the same as existed for the prior structure even if the prior structure was
       nonconforming in height. NO ADDITIONAL HEIGHT SHALL BE ALLOWED for the
       replacement structure if it has a nonconforming height. A conforming
       structure shall not be granted an additional height increase if it creates
       a nonconforming height."

    So: if the prior beach house was nonconforming in height — common on old Malibu
    beach stock — the +10% height allowance is GONE ENTIRELY, Issue No. 10 or not.
    And if the wave-uprush floor pushes you over, the DMW gives you nothing and
    you're at a full CDP.

    This one fact decides whether the Issue No. 10 downside is a fee or a redesign.
    Get it from the survey and the permit record BEFORE closing.
    """
    if conforming is None:
        return ("<b>PRIOR HEIGHT CONFORMITY — get this before you close.</b> Was the prior "
                "structure conforming in height? Not in the county record. This single fact "
                "decides whether the Issue No. 10 downside is a fee or a redesign.<br>"
                "If the prior structure was <b>nonconforming in height</b>, the certified "
                "de minimis waiver (LIP 13.4.11(A)(4)) allows <b>no additional height at "
                "all</b> — the +10% height allowance is gone regardless of Issue No. 10. And "
                "if a wave-uprush floor pushes you over, the DMW gives you nothing and you're "
                "at a full CDP. Old Malibu beach stock is frequently nonconforming. Get it "
                "from the survey and permit record.")
    if conforming is False:
        return ("<b>PRIOR STRUCTURE NONCONFORMING IN HEIGHT — the +10% height allowance is "
                "gone.</b> Per the certified DMW (LIP 13.4.11(A)(4)): 'No additional height "
                "shall be allowed for the replacement structure if it has a nonconforming "
                "height.' Spend the allowance laterally; there is no vertical option here. "
                "And the Issue No. 10 tail risk is concentrated on exactly these lots — if a "
                "wave-uprush floor drives elevation up, the DMW offers nothing and the "
                "fallback is a full CDP.")
    return ("<span class='cite'>Prior structure conforming in height. The certified DMW "
            "(LIP 13.4.11(A)(4)) is available as a fallback if Issue No. 10's FEMA-elevation "
            "reading is challenged — but note it may not grant an increase that would itself "
            "create a nonconforming height.</span>")


def pf1_check() -> str:
    """
    Issue No. PF1 — THE SLEEPER. Nobody is asking about this.

    "If a property owner had a deemed complete application prior to the fire, the
     property owner is allowed to construct both the replacement structure and the
     deemed complete application" — the combined result treated as the like-for-like.

    This is the one legitimate path to a materially larger envelope INSIDE the
    exemption, and it appears to attach to the property. If a lot has a
    deemed-complete addition in the file as of January 6 2025, that is a
    repriceable asset the seller very likely does not know they own.

    Ask every seller. It costs one question.
    """
    return ("<b>ASK THE SELLER: was there a deemed-complete application on file on "
            "January 6, 2025?</b> [Issue No. PF1]<br>"
            "If yes, the owner may construct <b>both</b> the replacement structure "
            "<b>and</b> the deemed-complete application, with the combined result treated as "
            "like-for-like. That is the only clean path to a materially larger envelope "
            "inside the exemption, and it appears to attach to the property.<br>"
            "<span class='cite'>Nobody is asking this. A lot with a deemed-complete addition "
            "in the file is a repriceable asset the seller probably doesn't know they own. "
            "One question per lot.</span><br><br>"
            "<b>Whether PF1 transfers to a purchaser is genuinely unresolved.</b> It's the one "
            "place in Interpretation No. 24 where 'property owner' plausibly does operative "
            "work — everywhere else the subject of the sentence is the structure; here it's an "
            "entitlement a specific person put into the City's system. Pending land use "
            "applications generally attach to the property and are assignable, and the City's "
            "FAQ says the rebuild rights go with the land. But a deemed-complete addition is "
            "the closest thing in the scheme to a personal benefit.<br><br>"
            "<b>Resolve it by email to Community Development — but not in the fund's name and "
            "not attached to an APN.</b> You do not want a written 'PF1 does not transfer' "
            "sitting in a file with your name on it: either as an adverse determination you "
            "then argue around, or as a document that surfaces in diligence when <i>you</i> "
            "are the seller. Neutral hypothetical, through the architect or counsel. Same "
            "answer, no record.<br>"
            "<span class='cite'>And if a lot's thesis <i>is</i> PF1, you're buying a legal "
            "opinion rather than dirt — structure the value into a price adjustment, not your "
            "basis.</span>")


def envelope(prior_sqft: float, prior_ceiling: float, proposed_ceiling: float,
             basement_sqft: float = 0.0, factor: float = 1.10):
    """
    Interp. No. 24, Issue No. 1 — THREE SIMULTANEOUS CEILINGS.
    "does not exceed 110 percent the bulk (volume), square footage, or height"

        buildable = min( prior_sqft x factor , (prior_volume x factor) / proposed_ceiling )

    The volume cap binds whenever proposed ceiling height > prior ceiling height.
    Basements and subterranean garages count toward the same 110% [Issue No. 5]
    and carry no finished exit value per sf.

    ---------------------------------------------------------------------------
    THE +10% IS DISCRETIONARY. THE LIKE-FOR-LIKE BASE IS NOT.
    ---------------------------------------------------------------------------
    Two different legal instruments are doing work here and they have different
    characters:

      LIP 13.4.6 (CDP exemption) is CRITERIA-BASED. Same use, within 10% of floor
      area / height / bulk, sited substantially in the same location. Meet the
      three tests and no permit is required. No discretion.

      MMC 17.60.020(C) as amended by Ordinance 524 (the zoning +10%) is
      DISCRETIONARY BY ITS OWN TERMS: structures "may be permitted, AT THE
      DISCRETION OF THE PLANNING DIRECTOR through approval of a planning
      verification, to increase the square footage, height or bulk permitted by
      this title by 10 percent."

    So a purchaser has the same right to like-for-like reconstruction as the
    pre-fire owner. The "+10%" half of "like-for-like +10%" is, on the face of the
    code, a discretionary grant. In practice it appears routine — Interpretation
    No. 24 spends twelve issues on HOW to calculate it, not WHETHER to give it.
    But underwriting it as certain is not supported by the code text, and it is
    the obvious lever if anyone wanted one.

    Pass factor=1.00 for the like-for-like base case. Model that standalone.
    """
    sqft_cap = prior_sqft * factor
    prior_volume = prior_sqft * prior_ceiling
    vol_cap = (prior_volume * factor) / proposed_ceiling
    gross = min(sqft_cap, vol_cap)
    binding = "SQUARE FOOTAGE" if sqft_cap <= vol_cap else "VOLUME (bulk)"
    habitable = gross - (basement_sqft or 0)
    return dict(
        gross=round(gross), habitable=round(habitable),
        sqft_cap=round(sqft_cap), vol_cap=round(vol_cap),
        binding=binding, prior_volume=round(prior_volume),
        haircut_vs_prior=(gross / prior_sqft) - 1.0,
        factor=factor,
        discretionary=(factor > 1.0),
    )


def envelope_both_cases(prior_sqft: float, prior_ceiling: float,
                        proposed_ceiling: float, basement_sqft: float = 0.0):
    """
    Both cases, always, because they have different legal characters.

    AS OF RIGHT  — like-for-like at 100%. Criteria-based under LIP 13.4.6.
    IF GRANTED   — the +10% at the Planning Director's discretion under
                   MMC 17.60.020(C) / Ordinance 524.

    A screen that prints only the 110% number is underwriting a discretionary
    grant as if it were an entitlement.
    """
    return dict(
        as_of_right=envelope(prior_sqft, prior_ceiling, proposed_ceiling,
                             basement_sqft, factor=1.00),
        if_granted=envelope(prior_sqft, prior_ceiling, proposed_ceiling,
                            basement_sqft, factor=1.10),
    )
