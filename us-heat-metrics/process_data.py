"""
process_data.py — US 7-city raw heat & social metrics pipeline (NO composite index)

Parameterized version of kano-heat-metrics/process_data.py: loops over every
city in cities_config.py that has a cached heat-metrics file, and writes each
city's raw metric values (no HES/SVS/HVI, no tiers) to its own data/<city>/ dir.

Heat variables also get a "climatology-relative" companion fraction
(<key>_climrel) — each tract's value expressed as a fraction of the distance
between ITS OWN historical reference mean and p99 (from the WMO reference
climatology), not the observed min/max across tracts in this run. The map
color scale for those variables uses the fixed, climatology-anchored
companion field; the raw value (°F/%/°C) is unchanged and still what's
displayed in tooltips/table/popups.

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

# Fixed climatology-anchored scale for LST anomaly coloring (°C): 0 = at
# normal (green), +8°C = extreme (red). Unlike the ERA5-derived heat
# variables, LST anomaly has no per-tract WMO percentile to key off, so this
# uses a single fixed absolute band instead of a per-tract ratio.
LST_ANOMALY_RED_AT_C = 8.0

# Fixed scale for extreme-day % coloring: a stationary climate would put ~5%
# of days above the historical p95 threshold by construction, so 0% = green
# and 40%+ = red treats "several times the expected base rate" as extreme.
EXTREME_PCT_RED_AT = 40.0

VARIABLE_KEYS = [
    "daytime_peak_f", "heat_anomaly_f", "extreme_pct", "nighttime_stress_f",
    "rwi_mean", "health_per_10k", "built_frac", "tree_frac", "canopy_frac_over_3m",
    "viirs_mean", "gdl_hdi", "population",
    "frac_under5", "frac_elderly_65plus", "frac_elderly_75plus", "old_age_dependency_ratio",
    "lst_anomaly_c", "ref_daytime_hi_mean", "ref_daytime_hi_p95",
]


def safe_mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def clip(v, lo, hi):
    return max(lo, min(hi, v))


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

        # WMO reference climatology, averaged over the same rolling window —
        # the benchmark this tract's heat values get compared against below,
        # and also exposed as their own selectable "Climatology" layers.
        ref_day_mean   = safe_mean([r["ref_daytime_hi_mean"]   for r in window if r["ref_daytime_hi_mean"]   is not None])
        ref_day_p95    = safe_mean([r["ref_daytime_hi_p95"]    for r in window if r["ref_daytime_hi_p95"]    is not None])
        ref_day_p99    = safe_mean([r["ref_daytime_hi_p99"]    for r in window if r["ref_daytime_hi_p99"]    is not None])
        ref_night_med  = safe_mean([r["ref_nighttime_hi_median"] for r in window if r["ref_nighttime_hi_median"] is not None])
        ref_night_p99  = safe_mean([r["ref_nighttime_hi_p99"]  for r in window if r["ref_nighttime_hi_p99"]  is not None])

        poly_heat[name] = {
            "heat_anomaly":     anomaly,
            "extreme_frac":     extreme_frac,
            "nighttime_stress": nt_stress,
            "daytime_peak":     safe_mean(peaks),
            "days_covered":     len(window),
            "population":       pops[0] if pops else None,
            "ref_day_mean":     ref_day_mean,
            "ref_day_p95":      ref_day_p95,
            "ref_day_p99":      ref_day_p99,
            "ref_night_med":    ref_night_med,
            "ref_night_p99":    ref_night_p99,
        }

    # ── raw vulnerability (no inversion/weighting) ──────────────────────────
    vuln_by_name = {v["name"]: v for v in raw_vuln}

    scores = {}
    for name, ph in poly_heat.items():
        v = vuln_by_name.get(name, {})

        daytime_peak_f     = round(ph["daytime_peak"],     1) if ph["daytime_peak"]     is not None else None
        heat_anomaly_f      = round(ph["heat_anomaly"],     1) if ph["heat_anomaly"]     is not None else None
        extreme_pct         = round(ph["extreme_frac"]*100, 0) if ph["extreme_frac"]     is not None else None
        nighttime_stress_f  = round(ph["nighttime_stress"], 1) if ph["nighttime_stress"] is not None else None
        lst_anomaly_c       = round(v["lst_warm_season_anomaly_c"], 2) if v.get("lst_warm_season_anomaly_c") is not None else None

        # ── climatology-relative fractions (fixed, WMO-benchmark-anchored
        # scale, NOT this-run's observed min/max) — used for map color only.
        day_spread = (ph["ref_day_p99"] - ph["ref_day_mean"]) if (ph["ref_day_p99"] is not None and ph["ref_day_mean"] is not None) else None
        night_spread = (ph["ref_night_p99"] - ph["ref_night_med"]) if (ph["ref_night_p99"] is not None and ph["ref_night_med"] is not None) else None

        daytime_peak_climrel = (
            clip((ph["daytime_peak"] - ph["ref_day_mean"]) / day_spread, -0.3, 1.3)
            if daytime_peak_f is not None and day_spread and day_spread > 0 else None
        )
        heat_anomaly_climrel = (
            clip(ph["heat_anomaly"] / day_spread, -0.3, 1.3)
            if heat_anomaly_f is not None and day_spread and day_spread > 0 else None
        )
        nighttime_stress_climrel = (
            clip(ph["nighttime_stress"] / night_spread, -0.3, 1.3)
            if nighttime_stress_f is not None and night_spread and night_spread > 0 else None
        )
        extreme_pct_climrel = clip(extreme_pct / EXTREME_PCT_RED_AT, 0, 1) if extreme_pct is not None else None
        lst_anomaly_climrel = clip(lst_anomaly_c / LST_ANOMALY_RED_AT_C, 0, 1) if lst_anomaly_c is not None else None

        scores[name] = {
            "population":     ph["population"],
            "days_covered":   ph["days_covered"],
            "daytime_peak_f":     daytime_peak_f,
            "heat_anomaly_f":     heat_anomaly_f,
            "extreme_pct":        extreme_pct,
            "nighttime_stress_f": nighttime_stress_f,
            "daytime_peak_f_climrel":     round(daytime_peak_climrel, 4)     if daytime_peak_climrel     is not None else None,
            "heat_anomaly_f_climrel":     round(heat_anomaly_climrel, 4)     if heat_anomaly_climrel     is not None else None,
            "nighttime_stress_f_climrel": round(nighttime_stress_climrel, 4) if nighttime_stress_climrel is not None else None,
            "extreme_pct_climrel":        round(extreme_pct_climrel, 4)      if extreme_pct_climrel      is not None else None,
            "ref_daytime_hi_mean": round(ph["ref_day_mean"], 1) if ph["ref_day_mean"] is not None else None,
            "ref_daytime_hi_p95":  round(ph["ref_day_p95"],  1) if ph["ref_day_p95"]  is not None else None,
            "rwi_mean":       v.get("rwi_mean"),
            "health_per_10k": v.get("health_facility_per_10k"),
            "built_frac":     round(v["wc_built_frac"], 3) if v.get("wc_built_frac") is not None else None,
            "tree_frac":      round(v["wc_tree_frac"],  3) if v.get("wc_tree_frac")  is not None else None,
            "canopy_frac_over_3m": round(v["canopy_frac_over_3m"], 3) if v.get("canopy_frac_over_3m") is not None else None,
            "viirs_mean":     round(v["viirs_mean"], 1)    if v.get("viirs_mean")    is not None else None,
            "gdl_hdi":        v.get("gdl_hdi"),
            "gdl_region":     v.get("gdl_region_name"),
            "ghsl_smod":      v.get("ghsl_smod_dominant"),
            "lst_anomaly_c":  lst_anomaly_c,
            "lst_anomaly_c_climrel": round(lst_anomaly_climrel, 4) if lst_anomaly_climrel is not None else None,
            "worldpop_pop_total":     round(v["worldpop_pop_total"], 0) if v.get("worldpop_pop_total") is not None else None,
            "frac_under5":            round(v["frac_under5"]*100, 1)         if v.get("frac_under5")         is not None else None,
            "frac_elderly_65plus":    round(v["frac_elderly_65plus"]*100, 1) if v.get("frac_elderly_65plus") is not None else None,
            "frac_elderly_75plus":    round(v["frac_elderly_75plus"]*100, 1) if v.get("frac_elderly_75plus") is not None else None,
            "old_age_dependency_ratio": round(v["old_age_dependency_ratio"], 3) if v.get("old_age_dependency_ratio") is not None else None,
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

    # ── per-variable stats (raw values only — climrel fields use a fixed
    # scale, not data-driven, so they're excluded from this table) ─────────
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
