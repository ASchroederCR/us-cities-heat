"""
build_data.py — uses the full Boston/Cambridge metro area (all of Suffolk +
Middlesex counties, 591 census tracts, already covered by the
boston-cambridge-2026 API project) and adds day-level (not rolling-window)
heat values so the standalone map can drive a time slider.

Earlier versions of this script filtered down to just Cambridge (33 tracts)
and then Cambridge + 5 adjacent towns (99 tracts), but both were too
geographically compact to span more than ~2 ERA5 grid cells — the heat
layers barely varied. The full metro area spans ~28 distinct daily values,
which is why this now uses the whole AOI file with no GEOID filtering.

Reads:  ../boston_heat_metrics.json      (shared cache w/ us-heat-metrics/boston)
        ../boston_vulnerability.json
        ../Cities_USA/aoi/boston_tract_aoi.geojson
Writes: data/static.geojson   (591 features, static vulnerability/demographic properties)
        data/daily.json       (per-tract array of day-level heat values)
        data/last_run.json    (metadata + classification stats)
"""

import json
import os
import statistics
from collections import defaultdict
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

HEAT_FILE = os.path.join(BASE, "..", "boston_heat_metrics.json")
VULN_FILE = os.path.join(BASE, "..", "boston_vulnerability.json")
GEO_FILE  = os.path.join(BASE, "..", "Cities_USA", "aoi", "boston_tract_aoi.geojson")

STATIC_KEYS = [
    "built_frac", "tree_frac", "viirs_mean", "gdl_hdi",
    "frac_under5", "frac_elderly_65plus", "lst_anomaly_c", "population",
]


def safe_round(v, n):
    return round(v, n) if v is not None else None


print("Loading source data...")
with open(HEAT_FILE) as f:
    raw_metrics = json.load(f)
with open(VULN_FILE) as f:
    raw_vuln = json.load(f)
with open(GEO_FILE) as f:
    geojson = json.load(f)

# ── 1. use the full metro area — no filtering ───────────────────────────────
cam_features = geojson["features"]
cam_names = {f["properties"]["name"] for f in cam_features}
print(f"  {len(cam_features)} metro-area tracts")

vuln_by_name = {v["name"]: v for v in raw_vuln if v["name"] in cam_names}

# ── 2. day-level heat values (not rolling-window aggregates) ───────────────
poly_rows = defaultdict(list)
for row in raw_metrics:
    if row["name"] in cam_names:
        poly_rows[row["name"]].append(row)

daily = {}
for name, rows in poly_rows.items():
    series = []
    for r in sorted(rows, key=lambda x: x["date"]):
        dt_max   = r.get("daytime_hi_max")
        ref_mean = r.get("ref_daytime_hi_mean")
        ref_p95  = r.get("ref_daytime_hi_p95")
        nt_mean  = r.get("nighttime_hi_mean")
        ref_nt   = r.get("ref_nighttime_hi_median")
        series.append({
            "date":            r["date"],
            "daytime_peak_f":  safe_round(dt_max, 1),
            "heat_anomaly_f":  safe_round(dt_max - ref_mean, 1) if dt_max is not None and ref_mean is not None else None,
            "is_extreme":      bool(dt_max is not None and ref_p95 is not None and dt_max > ref_p95),
            "nighttime_stress_f": safe_round(nt_mean - ref_nt, 1) if nt_mean is not None and ref_nt is not None else None,
            "ref_daytime_hi_p95":  safe_round(ref_p95, 1),
            "ref_daytime_hi_mean": safe_round(ref_mean, 1),
        })
    daily[name] = series

with open(os.path.join(DATA, "daily.json"), "w") as f:
    json.dump(daily, f, separators=(",", ":"))
print(f"  daily.json — {len(daily)} tracts")

# ── 3. static properties (vulnerability / demographic, one value per tract) ─
for feature in cam_features:
    name = feature["properties"]["name"]
    v = vuln_by_name.get(name, {})
    pops = [r["population"] for r in poly_rows.get(name, []) if r.get("population") is not None]

    feature["properties"].update({
        "population":              pops[0] if pops else None,
        "built_frac":              safe_round(v.get("wc_built_frac"), 3),
        "tree_frac":               safe_round(v.get("wc_tree_frac"), 3),
        "viirs_mean":              safe_round(v.get("viirs_mean"), 1),
        "gdl_hdi":                 v.get("gdl_hdi"),
        "gdl_region":              v.get("gdl_region_name"),
        "frac_under5":             safe_round(v["frac_under5"]*100, 1) if v.get("frac_under5") is not None else None,
        "frac_elderly_65plus":     safe_round(v["frac_elderly_65plus"]*100, 1) if v.get("frac_elderly_65plus") is not None else None,
        "lst_anomaly_c":           safe_round(v.get("lst_warm_season_anomaly_c"), 2),
        "has_data": name in daily,
    })

with open(os.path.join(DATA, "static.geojson"), "w") as f:
    json.dump({"type": "FeatureCollection", "features": cam_features}, f, separators=(",", ":"))
print(f"  static.geojson — {len(cam_features)} features")

# ── 4. classification stats ─────────────────────────────────────────────────
# Daily variables: computed across ALL tract-days combined, so the color
# scale is stable while scrubbing the time slider (same color = same value
# range on every day, not recomputed per-day).
daily_keys = ["daytime_peak_f", "heat_anomaly_f", "nighttime_stress_f"]
all_dates = sorted({d["date"] for series in daily.values() for d in series})

daily_stats = {}
for key in daily_keys:
    vals = [d[key] for series in daily.values() for d in series if d[key] is not None]
    daily_stats[key] = {"min": round(min(vals), 2), "max": round(max(vals), 2), "mean": round(statistics.mean(vals), 2)} if vals else {"min": None, "max": None, "mean": None}

static_stats = {}
for key in STATIC_KEYS:
    vals = [f["properties"][key] for f in cam_features if f["properties"].get(key) is not None]
    static_stats[key] = {"min": round(min(vals), 4), "max": round(max(vals), 4), "mean": round(statistics.mean(vals), 4)} if vals else {"min": None, "max": None, "mean": None}

total_pop = sum(f["properties"]["population"] or 0 for f in cam_features)
extreme_day_count = sum(1 for series in daily.values() for d in series if d["is_extreme"])

summary = {
    "last_updated":        str(date.today()),
    "data_date_range":     [all_dates[0], all_dates[-1]],
    "tract_count":         len(cam_features),
    "total_population":    total_pop,
    "daily_stats":         daily_stats,
    "static_stats":        static_stats,
    "extreme_tract_days":  extreme_day_count,
    "map_center":          [42.42, -71.25],
    "map_zoom":            10,
}

with open(os.path.join(DATA, "last_run.json"), "w") as f:
    json.dump(summary, f, indent=2)
print(f"  last_run.json — range {all_dates[0]}..{all_dates[-1]}, {len(all_dates)} days")
print("Done.")
