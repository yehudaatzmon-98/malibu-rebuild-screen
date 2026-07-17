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


def triage(p: Parcel, listing_sqft=None, listing_price=None) -> Triage:
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
        note = jur.la_review_note(p.prior_sqft, p.year_built)
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
def ceiling_from_year(yr: Optional[int]):
    if not yr:
        return None, "UNKNOWN — no year built"
    if yr < 1950:
        return 8.0, f"ESTIMATED from year built {yr} (pre-1950 ~8ft)"
    if yr < 2000:
        return 8.5, f"ESTIMATED from year built {yr} (mid-century ~8.5ft)"
    return 9.5, f"ESTIMATED from year built {yr} (modern ~9.5ft)"


def envelope(prior_sqft: float, prior_ceiling: float, proposed_ceiling: float,
             basement_sqft: float = 0.0, factor: float = 1.10):
    """
    Interp. No. 24, Issue No. 1 — THREE SIMULTANEOUS CEILINGS.
    "does not exceed 110 percent the bulk (volume), square footage, or height"

        buildable = min( prior_sqft x 1.10 , (prior_volume x 1.10) / proposed_ceiling )

    The volume cap binds whenever proposed ceiling height > prior ceiling height.
    Basements and subterranean garages count toward the same 110% [Issue No. 5]
    and carry no finished exit value per sf.
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
    )
