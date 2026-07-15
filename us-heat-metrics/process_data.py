"""
process_data.py — US 7-city raw heat & social metrics pipeline (NO composite index)

Parameterized version of kano-heat-metrics/process_data.py: loops over every
city in cities_config.py that has a cached heat-metrics file, and writes each
city's raw metric values (no HES/SVS/HVI, no tiers) to its own data/<city>/ dir.

Usage:
    py process_data.py            # process every city with a cache file present
    py process_data.py fresno     # process just one city (by key in cities_config.py)

Reads (per city):  ../<city>_heat_metrics.json
                    ../<city>_vulnerability.json
                    Cities_USA/aoi/<city>_tract_aoi.geojson
Writes (per city):  data/<city>/metrics.geojson
                     data/<city>/heat_timeseries.json
                     data/<city>/last_run.json
"""

import json
import os
import sys
import statistics
from collections import defaultdict
from datetime import date

from cities_config import CITIES, CITY_ORDER

BASE = os.path.dirname(os.path.abspath(__file__))

ROLLING_DAYS = 30

VARIABLE_KEYS = [
    "daytime_peak_f", "heat_anomaly_f", "extreme_pct", "nighttime_stress_f",
    "rwi_mean", "health_per_10k", "built_frac", "tree_frac", "viirs_mean",
    "gdl_hdi", "population",
]


def safe_mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def process_city(city_key, cfg):
    sub_projects = cfg["sub_projects"]
    heat_files = [os.path.join(BASE, sp["heat_cache"]) for sp in sub_projects]

    if not all(os.path.exists(f) for f in heat_files):
        missing = [sp["project_id"] for sp, f in zip(sub_projects, heat_files) if not os.path.exists(f)]
        print(f"[{city_key}] SKIP — no cached heat metrics yet for: {', '.join(missing)}")
        return

    data_dir = os.path.join(BASE, "data", city_key)
    os.makedirs(data_dir, exist_ok=True)

    print(f"[{city_key}] Loading data ({len(sub_projects)} sub-project(s))...")
    raw_metrics, raw_vuln, features = [], [], []
    for sp in sub_projects:
        with open(os.path.join(BASE, sp["heat_cache"])) as f:
            raw_metrics.extend(json.load(f))
        with open(os.path.join(BASE, sp["vuln_cache"])) as f:
            raw_vuln.extend(json.load(f))
        with open(os.path.join(BASE, sp["aoi_file"])) as f:
            features.extend(json.load(f)["features"])
    geojson = {"type": "FeatureCollection", "features": features}

    # ── time series ──────────────────────────────────────────────────────────
    all_dates = sorted(set(r["date"] for r in raw_metrics))
    if not all_dates:
        print(f"[{city_key}] SKIP — cache has 0 rows")
        return
    cutoff = all_dates[-ROLLING_DAYS] if len(all_dates) > ROLLING_DAYS else all_dates[0]

    poly_rows = defaultdict(list)
    for row in raw_metrics:
        poly_rows[row["name"]].append(row)

    timeseries = {}
    for name, rows in poly_rows.items():
        timeseries[name] = sorted(
            [
                {
                    "date":             r["date"],
                    "daytime_hi_max":   r["daytime_hi_max"],
                    "daytime_hi_mean":  r["daytime_hi_mean"],
                    "nighttime_hi_mean":r["nighttime_hi_mean"],
                    "day_t2m_max":      r["day_t2m_max"],
                    "ref_daytime_hi_p95": r["ref_daytime_hi_p95"],
                    "ref_daytime_hi_mean": r["ref_daytime_hi_mean"],
                }
                for r in rows
            ],
            key=lambda x: x["date"],
        )

    with open(os.path.join(data_dir, "heat_timeseries.json"), "w") as f:
        json.dump(timeseries, f, separators=(",", ":"))

    # ── raw heat aggregates (rolling window) ────────────────────────────────
    poly_heat = {}
    for name, rows in poly_rows.items():
        window = [r for r in rows if r["date"] >= cutoff]
        if not window:
            window = rows

        anomaly = safe_mean([
            r["daytime_hi_max"] - r["ref_daytime_hi_mean"]
            for r in window
            if r["daytime_hi_max"] is not None and r["ref_daytime_hi_mean"] is not None
        ])
        extreme_pairs = [
            (r["daytime_hi_max"], r["ref_daytime_hi_p95"])
            for r in window
            if r["daytime_hi_max"] is not None and r["ref_daytime_hi_p95"] is not None
        ]
        extreme_frac = (
            sum(1 for v, t in extreme_pairs if v > t) / len(extreme_pairs)
            if extreme_pairs else None
        )
        nt_stress = safe_mean([
            r["nighttime_hi_mean"] - r["ref_nighttime_hi_median"]
            for r in window
            if r["nighttime_hi_mean"] is not None and r["ref_nighttime_hi_median"] is not None
        ])
        peaks = [r["daytime_hi_max"] for r in window if r["daytime_hi_max"] is not None]
        pops  = [r["population"]     for r in rows   if r["population"]     is not None]

        poly_heat[name] = {
            "heat_anomaly":     anomaly,
            "extreme_frac":     extreme_frac,
            "nighttime_stress": nt_stress,
            "daytime_peak":     safe_mean(peaks),
            "days_covered":     len(window),
            "population":       pops[0] if pops else None,
        }

    # ── raw vulnerability (no inversion/weighting) ──────────────────────────
    vuln_by_name = {v["name"]: v for v in raw_vuln}

    scores = {}
    for name, ph in poly_heat.items():
        v = vuln_by_name.get(name, {})
        scores[name] = {
            "population":     ph["population"],
            "days_covered":   ph["days_covered"],
            "daytime_peak_f":     round(ph["daytime_peak"],     1) if ph["daytime_peak"]     is not None else None,
            "heat_anomaly_f":     round(ph["heat_anomaly"],     1) if ph["heat_anomaly"]     is not None else None,
            "extreme_pct":        round(ph["extreme_frac"]*100, 0) if ph["extreme_frac"]     is not None else None,
            "nighttime_stress_f": round(ph["nighttime_stress"], 1) if ph["nighttime_stress"] is not None else None,
            "rwi_mean":       v.get("rwi_mean"),
            "health_per_10k": v.get("health_facility_per_10k"),
            "built_frac":     round(v["wc_built_frac"], 3) if v.get("wc_built_frac") is not None else None,
            "tree_frac":      round(v["wc_tree_frac"],  3) if v.get("wc_tree_frac")  is not None else None,
            "viirs_mean":     round(v["viirs_mean"], 1)    if v.get("viirs_mean")    is not None else None,
            "gdl_hdi":        v.get("gdl_hdi"),
            "gdl_region":     v.get("gdl_region_name"),
            "ghsl_smod":      v.get("ghsl_smod_dominant"),
        }

    # ── inject into GeoJSON ──────────────────────────────────────────────────
    geojson = dict(geojson)
    matched = unmatched = 0
    for feature in geojson["features"]:
        geo_name = feature["properties"]["name"]
        s = scores.get(geo_name)
        if s:
            feature["properties"].update(s)
            feature["properties"]["has_data"] = True
            matched += 1
        else:
            feature["properties"]["has_data"] = False
            unmatched += 1

    with open(os.path.join(data_dir, "metrics.geojson"), "w") as f:
        json.dump(geojson, f, separators=(",", ":"))

    # ── per-variable stats ────────────────────────────────────────────────────
    variable_stats = {}
    for key in VARIABLE_KEYS:
        vals = [s[key] for s in scores.values() if s.get(key) is not None]
        if vals:
            variable_stats[key] = {
                "min": round(min(vals), 4), "max": round(max(vals), 4),
                "mean": round(statistics.mean(vals), 4),
            }
        else:
            variable_stats[key] = {"min": None, "max": None, "mean": None}

    total_pop = sum(s["population"] or 0 for s in scores.values())
    daytime_vals = [s["daytime_peak_f"] for s in scores.values() if s["daytime_peak_f"]]

    summary = {
        "city_key":             city_key,
        "city_label":           cfg["label"],
        "last_updated":         str(date.today()),
        "data_date_range":      [all_dates[0], all_dates[-1]],
        "rolling_window_days":  ROLLING_DAYS,
        "polygon_count":        len(scores),
        "total_population":     total_pop,
        "variable_stats":       variable_stats,
        "city_daytime_hi_mean": round(statistics.mean(daytime_vals), 1) if daytime_vals else None,
        "map_center":           cfg["map_center"],
        "map_zoom":             cfg["map_zoom"],
    }

    with open(os.path.join(data_dir, "last_run.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[{city_key}] {matched} polygons scored, {unmatched} no-data, "
          f"range {all_dates[0]}..{all_dates[-1]}")


def main():
    requested = sys.argv[1:]
    keys = requested if requested else CITY_ORDER
    for key in keys:
        if key not in CITIES:
            print(f"[{key}] unknown city key, skipping")
            continue
        process_city(key, CITIES[key])


if __name__ == "__main__":
    main()
