"""Finds the healthcare facilities closest to a location. No machine learning involved."""
import os
import re

import numpy as np
import pandas as pd

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "facilities.csv")

# Rough box around Uganda, used to reject locations that are clearly somewhere else
UGANDA_LAT, UGANDA_LON = (-1.5, 4.3), (29.5, 35.1)

# The "services" column is free text ("Maternity", "Maternity Care", "Maternal Care" ...),
# so each choice in the form searches for several spellings.
SERVICE_GROUPS = {
    "Maternity and antenatal care": ["matern", "antenatal", "postnatal", "obstetric", "delivery"],
    "Child health and immunisation": ["child", "pediatric", "paediatric", "immuniz", "immunis", "vaccin"],
    "Laboratory": ["lab"],
    "Pharmacy": ["pharm"],
    "X-ray and imaging": ["x-ray", "xray", "radiolog", "imaging", "ultrasound"],
    "Surgery": ["surg"],
    "Inpatient (overnight stay)": ["inpatient"],
    "Outpatient": ["outpatient", "opd"],
    "Family planning": ["family planning"],
    "HIV/AIDS care": ["hiv"],
    "Eye care": ["ophthal", "eye"],
    "Mental health": ["behavioral", "mental", "psych"],
    "Dental": ["dental", "dentist"],
    "Rehabilitation": ["rehab", "physio"],
}

# Loaded once when the app starts
all_facilities = pd.read_csv(DATA_PATH)

# Two kinds of facility are left out of the search because their coordinates can't be trusted
# (see step 7 of clean_data.py): sending someone to a clinic that probably isn't where the map
# says it is would do harm.
#   - the coordinates are shared by 5+ facilities (an area-level placeholder, not a building)
#   - the coordinates are 50+ km from the facility's own subcounty
PLACEHOLDER_IF_SHARED_BY = 5
reliable = (all_facilities["location_shared_by"] < PLACEHOLDER_IF_SHARED_BY) & ~all_facilities["location_mismatch"]
facilities = all_facilities[reliable].copy()
TOTAL = len(facilities)
facilities["services"] = facilities["services"].fillna("")
facilities["Subcounty"] = facilities["Subcounty"].fillna("unknown")
_services_lower = facilities["services"].str.lower()

SERVICES = list(SERVICE_GROUPS)
CARE_SYSTEMS = sorted(facilities["care_system"].dropna().unique())
SUBCOUNTIES = sorted(s for s in facilities["Subcounty"].unique() if s.lower() != "unknown")

# A subcounty's "centre" is the middle (median) of its facilities' coordinates
_centres = facilities.groupby("Subcounty")[["latitude", "longitude"]].median()
_by_lower_name = {name.lower(): name for name in SUBCOUNTIES}


def in_uganda(lat, lon):
    return UGANDA_LAT[0] <= lat <= UGANDA_LAT[1] and UGANDA_LON[0] <= lon <= UGANDA_LON[1]


def subcounty_centre(name):
    """Return (lat, lon) for a subcounty typed by the user, or None if it isn't in the data."""
    key = _by_lower_name.get((name or "").strip().lower())
    if key is None:
        return None
    row = _centres.loc[key]
    return float(row["latitude"]), float(row["longitude"])


def tidy_hours(text):
    """Turn the long 'Monday: ..., Tuesday: ...' string into something short to read."""
    if not isinstance(text, str) or not text.strip():
        return "Opening hours not listed"
    days = [p.strip() for p in re.split(r",(?=\s*[A-Za-z]+day:)", text)]
    values = {d.split(":", 1)[1].strip() for d in days if ":" in d}
    if len(values) == 1:
        return f"Every day: {values.pop()}"
    return "; ".join(f"{d[:3]}{d[d.index(':'):]}" if ":" in d else d for d in days)


def nearby(lat, lon, service=None, care_system=None, n=10):
    """Return the n closest facilities as a list of dicts, nearest first."""
    mask = pd.Series(True, index=facilities.index)
    if service in SERVICE_GROUPS:
        pattern = "|".join(re.escape(k) for k in SERVICE_GROUPS[service])
        mask &= _services_lower.str.contains(pattern, regex=True)
    if care_system:
        mask &= facilities["care_system"] == care_system

    df = facilities[mask].copy()

    # Haversine formula: distance in km between two points on the Earth
    phi1, phi2 = np.radians(lat), np.radians(df["latitude"])
    d_phi = phi2 - phi1
    d_lam = np.radians(df["longitude"] - lon)
    a = np.sin(d_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(d_lam / 2) ** 2
    df["distance_km"] = 6371 * 2 * np.arcsin(np.sqrt(a))

    results = []
    for _, r in df.nsmallest(n, "distance_km").iterrows():
        results.append({
            "name": r["facility_name"],
            "care_system": r["care_system"],
            "distance_km": round(float(r["distance_km"]), 1),
            "services": r["services"],
            "hours": tidy_hours(r["operating_hours"]),
            "phone": r["phone_number"] if pd.notna(r["phone_number"]) else None,
            "website": r["website"] if pd.notna(r["website"]) else None,
            "rating": float(r["rating"]) if pd.notna(r["rating"]) else None,
            "subcounty": r["Subcounty"],
            "map_url": f"https://www.google.com/maps/search/?api=1&query={r['latitude']},{r['longitude']}",
        })
    return results


# Numbers from the cleaning step (the printed output of clean_data.py).
# The app only loads the cleaned file, so these can't be worked out here.
CLEANING = {"raw_rows": 6520, "exact_duplicates": 51, "same_name_and_location": 57, "outside_uganda": 3}


def audit_summary():
    """Numbers for the data audit page, worked out from the cleaned file."""
    df = all_facilities
    n = len(df)
    shared = df["location_shared_by"] >= PLACEHOLDER_IF_SHARED_BY
    mismatch = df["location_mismatch"]
    reliable = ~(shared | mismatch)
    govt = df["care_system"] == "Government"

    def pct(count):
        return round(100 * float(count) / n, 1)

    segments = [
        {"label": "Location looks reliable", "count": int(reliable.sum()), "cls": "ok"},
        {"label": "Same coordinates as 4+ other facilities", "count": int((shared & ~mismatch).sum()), "cls": "bad1"},
        {"label": "Far from its own subcounty", "count": int((mismatch & ~shared).sum()), "cls": "bad2"},
        {"label": "Both problems", "count": int((shared & mismatch).sum()), "cls": "bad3"},
    ]
    for s in segments:
        s["pct"] = pct(s["count"])

    mix = []
    for name in ["Government", "Private for-profit", "Private not-for-profit"]:
        mix.append({
            "name": name,
            "all": round(100 * float((df["care_system"] == name).mean()), 1),
            "kept": round(100 * float((df.loc[reliable, "care_system"] == name).mean()), 1),
        })

    missing = [
        {"name": "No opening hours", "pct": round(100 * float(df["operating_hours"].isna().mean()), 1)},
        {"name": "No rating", "pct": round(100 * float(df["rating"].isna().mean()), 1)},
        {"name": "No phone number", "pct": round(100 * float(df["phone_number"].isna().mean()), 1)},
        {"name": "No website", "pct": round(100 * float(df["website"].isna().mean()), 1)},
    ]

    return {
        "n": n,
        "raw": CLEANING["raw_rows"],
        "cleaning": CLEANING,
        "segments": segments,
        "n_reliable": int(reliable.sum()),
        "reliable_pct": pct(reliable.sum()),
        "shared": int(shared.sum()),
        "shared_pct": pct(shared.sum()),
        "largest_group": int(df["location_shared_by"].max()),
        "mismatch": int(mismatch.sum()),
        "mismatch_pct": pct(mismatch.sum()),
        "mix": mix,
        "govt_total": int(govt.sum()),
        "govt_excluded": round(100 * float((govt & ~reliable).sum()) / float(govt.sum()), 1),
        "other_excluded": round(100 * float((~govt & ~reliable).sum()) / float((~govt).sum()), 1),
        "missing": missing,
        "payment_values": int(df["mode of payment"].nunique()),
        "payment_value": str(df["mode of payment"].dropna().iloc[0]),
    }