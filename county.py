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
    if ls <= 0:
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
        # The rule is known and cited. The INPUT it needs (prior footprint) is not
        # published by the Assessor. Name the rule, name the gap, refuse the number.
        # The discrepancy check runs FIRST and runs everywhere — it is the most
        # valuable output the tool has and it is not Malibu-specific.
        note = jur.la_review_note(p.prior_sqft, p.year_built, storeys)
        d = _discrepancy(p, listing_sqft)
        if d:
            note = f"{d}<br><br>{note}"
        return Triage("REVIEW", note, j.rulebook, j.code)

    # --- City of Malibu: Interpretation No. 24 ---
    if not p.prior_sqft:
        return Triage(
            "UNSCOREABLE",
            "County shows no prior structure square footage. Like-for-like relief is "
            "granted by reference to what burned — with no prior sqft there is no "
            "envelope to compute. If the Assessor listed the parcel as vacant BEFORE "
            "the fire, any structure on it is deemed illegal.",
            "Interp. No. 24, Issue No. 4", jur.MALIBU)

    if p.units and p.units > 1:
        return Triage(
            "EXCLUDED",
            f"County shows {p.units} units. Converting multifamily to a single-family "
            f"home triggers No Net Loss — the lost units must be replaced as ADUs, "
            f"which consume envelope. Not single-family underwriting.",
            "Interp. No. 24, Issue No. 8 / SB 166", jur.MALIBU)

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


def spr_check(is_beachfront: Optional[bool], proposed_ceiling: float,
              storeys_proposed: int = 1) -> Optional[str]:
    """
    Interpretation No. 24, Issue No. 9 — THE +10% IS NOT ALWAYS MINISTERIAL.

    The 10% increases must comply with current zoning. On NON-BEACHFRONT properties,
    an increase to height or bulk above 18 feet requires SITE PLAN REVIEW
    (MMC 17.62.040). Increases into required setbacks likewise require SPR, with de
    minimis encroachments possible at Director / Planning Manager discretion.

    WHY THIS MATTERS MORE THAN IT LOOKS
    Five of the seven PCH lots in the current set are Las Flores — non-beachfront.
    So on the majority of the set the "express" +10% is a DISCRETIONARY approval
    carrying timeline and denial risk, not an automatic one.

    It also compounds with the ceiling-height election: raising ceilings is exactly
    what drives height above 18ft. The move that shrinks the envelope via the volume
    cap is the same move that triggers SPR. The two constraints bite together.

    Beachfront status is NOT in the county record. It has to be supplied — it is
    determinable per parcel from the City's GIS layers.
    """
    if is_beachfront is None:
        return ("<b>SPR STATUS UNKNOWN.</b> Beachfront or not? Not in the county record. "
                "If this lot is NON-beachfront, any increase to height or bulk above 18ft "
                "requires Site Plan Review [Issue No. 9] — meaning the +10% is "
                "discretionary, not ministerial, with timeline and denial risk. "
                "Determinable per parcel from the City's GIS appeal-zone / beachfront "
                "layers. Five of the seven current PCH lots are Las Flores, non-beachfront.")
    if is_beachfront:
        return None
    est_height = proposed_ceiling * storeys_proposed
    if est_height > 18:
        return (f"<b>SITE PLAN REVIEW REQUIRED [Issue No. 9].</b> Non-beachfront, and "
                f"{storeys_proposed} storey(s) at {proposed_ceiling}ft is ~{est_height:.0f}ft "
                f"— above the 18ft threshold (MMC 17.62.040). <b>The +10% here is a "
                f"discretionary approval, not ministerial.</b> Carries timeline and denial "
                f"risk that the express-lane framing does not. Note this compounds with the "
                f"ceiling election: raising ceilings shrinks the envelope via the volume cap "
                f"AND triggers SPR.")
    return (f"<span class='cite'>Non-beachfront, ~{est_height:.0f}ft proposed — under the "
            f"18ft SPR threshold [Issue No. 9]. Setback encroachments would still "
            f"trigger review.</span>")


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
