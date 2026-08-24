"""
Certificate of Occupancy parser.
================================

WHY THIS EXISTS

The LADBS record is the only trustworthy source for prior square footage — five out
of five working-sheet figures were wrong when checked, always overstated. But
pulling it is manual: LADBS blocks automated access, so somebody opens the page,
opens the PDF, and reads the numbers.

The waste isn't the lookup, it's what happens after. One C of O carries eight to ten
fields that the model needs — floor area, stories, height, basement levels, lot size,
lot type, Coastal Zone, Hillside Ordinance, environmentally sensitive area, fire
district — and until now there was nowhere to put any of it. It got read out loud
once and lost.

This turns that into: select the text on the PDF, copy, paste. Everything the model
needs is extracted and tagged CERTIFIED.

WHAT IT HANDLES

LADBS certificates print a structural inventory as two columns, CHANGED and TOTAL:

    Stories              0 Stories        2 Stories
    Basement             0 Levels         1 Levels
    Height (ZC)          10 Feet          31.75 Feet
    Floor Area (ZC)      2196.2 Sqft

TOTAL is the state of the building after the permit; CHANGED is what that permit
altered. Where both are present the parser takes TOTAL. Where only one figure
appears it is the change, which matters: on 865 Oreo the 2005 permits show a CHANGED
floor area of 2,196.2 sf with no total, and the earlier certificate shows a TOTAL of
2,006 sf. The building is the sum, roughly 4,202 sf, and the parser flags that case
rather than silently reporting one of them.
"""
from __future__ import annotations
import re
from typing import Optional


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _last_number_on_line(line: str) -> Optional[float]:
    """LADBS prints CHANGED then TOTAL. The last figure is the resulting state."""
    nums = re.findall(r"(\d[\d,]*\.?\d*)", line)
    return _num(nums[-1]) if nums else None


def _all_numbers_on_line(line: str) -> list:
    return [n for n in (_num(x) for x in re.findall(r"(\d[\d,]*\.?\d*)", line)) if n is not None]


def parse_cofo(text: str) -> dict:
    """
    Extract the fields the model needs from pasted Certificate of Occupancy text.

    Returns a dict with the values found, a list of human-readable notes about
    anything ambiguous, and the raw matches for auditing.
    """
    if not text or not text.strip():
        return dict(ok=False, notes=["Nothing pasted."])

    out: dict = {}
    notes: list = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    blob = "\n".join(lines)

    # ---- certificate identity ----
    m = re.search(r"CERTIFICATE\s+NUMBER\s*[:\s]*(\d{3,})", blob, re.I)
    if m:
        out["cofo_number"] = m.group(1)
    m = re.search(r"ADDRESS[:\s]+([0-9].{4,60})", blob, re.I)
    if m:
        out["address"] = m.group(1).strip()
    m = re.search(r"(?:STATUS DATE|DATE)[:\s]+(\d{1,2}/\d{1,2}/\d{4})", blob, re.I)
    if m:
        out["cofo_date"] = m.group(1)

    # ---- structural inventory ----
    for line in lines:
        low = line.lower()

        if low.startswith("floor area") and "residential" not in low:
            vals = _all_numbers_on_line(line)
            # strip the "(ZC)" zoning-code marker so it isn't read as a value
            vals = [v for v in vals if v not in (0.0,)] or vals
            if vals:
                out["floor_area_sqft"] = vals[-1]
                out["floor_area_changed"] = vals[0] if len(vals) > 1 else vals[-1]
                if len(vals) == 1:
                    notes.append(
                        "Only one floor-area figure on this certificate. If it is a "
                        "CHANGED value from an addition permit, the building total is "
                        "this plus whatever the earlier certificate reported — check "
                        "for a second C of O before using it as the prior area.")

        elif low.startswith("residential floor area"):
            v = _last_number_on_line(line)
            if v:
                out["residential_floor_area"] = v

        elif low.startswith("stories"):
            v = _last_number_on_line(line)
            if v:
                out["stories"] = int(v)

        elif low.startswith("basement"):
            v = _last_number_on_line(line)
            if v is not None:
                out["basement_levels"] = int(v)

        elif low.startswith("height (zc)"):
            v = _last_number_on_line(line)
            if v:
                out["height_zc_ft"] = v

        elif low.startswith("height (bc)"):
            v = _last_number_on_line(line)
            if v:
                out["height_bc_ft"] = v

        elif low.startswith("u occ") or low.startswith("u1 occ"):
            v = _last_number_on_line(line)
            if v:
                out["garage_sqft"] = v

        elif low.startswith("dwelling unit"):
            v = _last_number_on_line(line)
            if v:
                out["dwelling_units"] = int(v)

        elif "parking req" in low:
            v = _last_number_on_line(line)
            if v is not None:
                out["parking_required"] = int(v)

    # ---- parcel information (page 2 of the certificate) ----
    def flag(pattern: str, key: str):
        m = re.search(pattern + r"\s*[:\s]+\s*(YES|NO)", blob, re.I)
        if m:
            out[key] = m.group(1).upper() == "YES"

    flag(r"Coastal Zone Cons\.? Act", "coastal_zone")
    flag(r"Hillside Ordinance", "hillside_ordinance")
    flag(r"Hillside Grading Area", "hillside_grading")
    flag(r"Environmentally Sensitive Area", "environmentally_sensitive")

    m = re.search(r"Coastal Zone Cons\.? Act[:\s]+(Categorical Exclusion|Calvo Exclusion"
                  r"[^\n]*|Single Permit[^\n]*)", blob, re.I)
    if m:
        out["coastal_detail"] = m.group(1).strip()
        notes.append(f"Coastal exclusion noted: {m.group(1).strip()}. This may permit "
                     f"development without a full Coastal Development Permit — confirm "
                     f"the applicable exclusion order.")

    m = re.search(r"Zone[:\s]+(R[0-9A-Z\-]+)", blob)
    if m:
        out["zone"] = m.group(1)
    m = re.search(r"Fire District[:\s]+([A-Z]+)", blob)
    if m:
        out["fire_district"] = m.group(1)
        if "VHFHSZ" in m.group(1).upper():
            notes.append("Very High Fire Hazard Severity Zone — insurance availability "
                         "is a gating item, not a footnote.")
    m = re.search(r"Lot Type[:\s]+(CORNER|INTERIOR|KEY|REVERSE[A-Z ]*|FLAG)", blob, re.I)
    if m:
        out["lot_type"] = m.group(1).upper()
        if m.group(1).upper() == "CORNER":
            notes.append("Corner lot — two front-yard setbacks apply in LA, which "
                         "reduces the buildable footprint below what the lot area suggests.")
    m = re.search(r"Easement[:\s]+([^\n]+)", blob, re.I)
    if m:
        out["easement"] = m.group(1).strip()

    # lot size, printed either as dimensions or as IRR
    m = re.search(r"Lot Size[:\s]+(\d[\d,\.]*)\s*'?\s*[xX]\s*(\d[\d,\.]*)", blob)
    if m:
        w, d = _num(m.group(1)), _num(m.group(2))
        if w and d:
            out["lot_width_ft"], out["lot_depth_ft"] = w, d
            out["lot_sqft"] = round(w * d)
    elif re.search(r"Lot Size[:\s]+IRR", blob, re.I):
        out["lot_irregular"] = True
        notes.append("Lot recorded as IRR (irregular) with no numeric area. The EO8 "
                     "zoning envelope needs a lot area — take it from the plot plan or "
                     "the title report.")

    # ---- derived: the prior area the model should use ----
    prior = out.get("floor_area_sqft")
    if prior:
        out["prior_sqft"] = prior
        out["prior_sqft_source"] = "CERTIFIED"
    if out.get("height_zc_ft"):
        out["prior_height_ft"] = out["height_zc_ft"]
        if out["height_zc_ft"] * 1.10 < 20:
            notes.append(
                f"Prior height {out['height_zc_ft']:.1f} ft caps the EO1 rebuild at "
                f"{out['height_zc_ft']*1.10:.1f} ft, which will not accommodate a second "
                f"storey. On this lot the EO8 zoning route is likely the only viable one.")
    if out.get("basement_levels"):
        notes.append(f"{out['basement_levels']} basement level(s) recorded. Under EO1 a "
                     f"basement adds neither footprint nor height, so it may sit on top "
                     f"of the rebuild envelope rather than inside it. Worth confirming.")

    out["ok"] = bool(prior or out.get("lot_sqft"))
    out["notes"] = notes
    if not out["ok"]:
        notes.append("No floor area or lot size found. Paste the full certificate "
                     "including the STRUCTURAL INVENTORY block.")
    return out


def extract_pdf_text(file_obj) -> dict:
    """
    Pull the text layer out of a Certificate of Occupancy PDF.

    LADBS prints two kinds. Certificates issued from roughly 2008 onward carry a
    real text layer and extract cleanly. Older ones — the 1952 permit cards, for
    instance — are scans of paper with no text at all, and no amount of parsing will
    read them. This reports which it got rather than silently returning nothing.
    """
    try:
        import pdfplumber
    except ImportError:
        return dict(ok=False, text="", note="pdfplumber is not installed.")
    try:
        with pdfplumber.open(file_obj) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
        text = "\n".join(pages)
    except Exception as e:
        return dict(ok=False, text="", note=f"Could not open the PDF: {e}")

    if len(text.strip()) < 200:
        return dict(ok=False, text=text, scanned=True, pages=len(pages), note=(
            "This PDF has no text layer — it is a scan of a paper record. Older "
            "certificates and 1952-era permit cards are usually scans. Read the "
            "figures off the image and enter them by hand, or request a typed copy "
            "from records.ladbs@lacity.org."))
    return dict(ok=True, text=text, pages=len(pages), scanned=False,
                note=f"Read {len(pages)} page(s), {len(text):,} characters.")


def parse_cofo_pdf(file_obj) -> dict:
    """Read a certificate PDF and parse it in one step."""
    ex = extract_pdf_text(file_obj)
    if not ex.get("ok"):
        return dict(ok=False, notes=[ex.get("note", "Could not read the PDF.")],
                    scanned=ex.get("scanned", False), raw_text=ex.get("text", ""))
    parsed = parse_cofo(ex["text"])
    parsed["raw_text"] = ex["text"]
    parsed.setdefault("notes", []).insert(0, ex["note"])
    return parsed


def to_csv_row(parsed: dict, address: str = "") -> dict:
    """Flatten a parsed certificate into the columns the analyzer reads."""
    return {
        "ADDRESS": address or parsed.get("address", ""),
        "PRIOR_SQFT": parsed.get("prior_sqft"),
        "PRIOR_HEIGHT_FT": parsed.get("prior_height_ft"),
        "PRIOR_STORIES": parsed.get("stories"),
        "BASEMENT_LEVELS": parsed.get("basement_levels"),
        "LOT_SQFT": parsed.get("lot_sqft"),
        "LOT_TYPE": parsed.get("lot_type"),
        "ZONE": parsed.get("zone"),
        "COASTAL_ZONE": parsed.get("coastal_zone"),
        "HILLSIDE": parsed.get("hillside_ordinance"),
        "ESA": parsed.get("environmentally_sensitive"),
        "FIRE_DISTRICT": parsed.get("fire_district"),
        "SOURCE": parsed.get("prior_sqft_source", "CERTIFIED"),
        "COFO_NUMBER": parsed.get("cofo_number"),
        "COFO_DATE": parsed.get("cofo_date"),
    }
