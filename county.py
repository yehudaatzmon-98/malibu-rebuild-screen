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


def realistic_program(prior_sqft: float, prior_ceiling: float, proposed_ceiling: float,
                      basement_sqft: float = 0.0):
    """
    What you can actually build without a CDP — the honest ceiling.

    The exemption envelope is not the whole story. Legitimate additions on top:

      ADU up to 1,000 sf (Ordinance 524's cap), with the garage (400 sf max) and
      attached exterior decks/overhangs EXCLUDED from that limit. AB 462 (urgency
      statute, 10 Oct 2025) eliminated Coastal Commission appeal authority over
      local CDPs for ADUs and imposed a 60-day local clock. SB 1077 required the
      Commission and HCD to publish coastal-zone ADU streamlining guidance by
      1 July 2026 — that date has passed; check what actually issued.

      This is the most underrated lever available. It does not consume the 110%.

    Also real but small: Issue No. PF3 (Palisades, beachfront) — interior access
    stairs required by code because of the new FEMA finished-floor don't count
    toward the 10%. A free staircase.

    Water tanks required by an agency are excluded from TDSF — note that is a TDSF
    exclusion, NOT a 110% exclusion, and it applies to tanks, not living space.
    Don't overread it.

    THE HONEST CONCLUSION
    On a 1,760 sf prior: ~1,936 sf primary + up to ~1,000 sf ADU = ~2,900 sf across
    TWO units, one an accessory unit with its own kitchen and entry.

    That is a well-located small house with a guest unit. It is not the thing that
    trades against Malibu beachfront comps. If the model needs a single integrated
    2,700+ sf luxury envelope, the exemption path does not produce it.

    The lot may still work — as a small-house thesis, priced against small-house
    comps, underwritten on speed and land basis rather than square footage. That is
    a real strategy. It is a different strategy.
    """
    both = envelope_both_cases(prior_sqft, prior_ceiling, proposed_ceiling, basement_sqft)
    primary_aor = both["as_of_right"]["habitable"]
    primary_ifg = both["if_granted"]["habitable"]
    adu_max = 1000
    return dict(
        primary_as_of_right=primary_aor,
        primary_if_granted=primary_ifg,
        adu_max=adu_max,
        garage_free=400,
        total_as_of_right=primary_aor + adu_max,
        total_if_granted=primary_ifg + adu_max,
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
            "spending the +10% vertically past 18ft. Director-level, not a hearing — but it "
            "notices owners within 500ft (min 10 developed properties), and the standard is "
            "'substantial evidence supports the findings' after consultation with six "
            "specialists. Model <b>3-6 months</b>, and treat that as an estimate: no reliable "
            "post-fire Malibu SPR cycle-time data exists.<br><br>"
            "<b>You probably don't need this.</b> The allowance is bulk-constrained — you "
            "generally can't have both height and area. Take the 10% laterally, keep the "
            "roofline at prior height, stay inside the original envelope, and SPR goes away. "
            "On the Las Flores lots that is close to free.<br><br>"
            "<span class='cite'>If you also RELOCATE the structure, Ordinance 524's new "
            "MMC 17.62.040(A)(13) applies and the notice radius goes to 1,000ft.</span>")


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
            "One question per lot.</span>")


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
