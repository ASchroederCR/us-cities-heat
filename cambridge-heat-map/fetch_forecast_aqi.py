"""
fetch_forecast_aqi.py — pulls Open-Meteo forecast rows and CAMS/OpenAQ air
quality data for boston-cambridge-2026 and caches them locally, so
build_data.py can merge them into the time-slider daily series.

Both are already backfilled on the API side (confirmed via
get-data-availability on 2026-07-16: forecast through 2026-07-21,
air quality through 2026-07-14) — this script just pulls what's there.
Re-run periodically to pick up new forecast issues / AQI days.

Writes: ../boston_forecast.json      (data_source='forecast' rows only)
        ../boston_air_quality.json   (daily PM2.5/PM10/O3/AQI per tract)
"""

import json
import os
import time
from datetime import date, timedelta

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(BASE, "..", "us-heat-metrics", "credentials.json")
PROJECT_ID = "boston-cambridge-2026"
PAGE_SIZE = 500
MAX_RETRIES = 6

with open(CREDS_FILE) as f:
    CREDS = json.load(f)


def api_call(action, payload=None):
    for attempt in range(MAX_RETRIES):
        r = requests.post(CREDS["api_url"], json={
            "username": CREDS["username"], "key": CREDS["key"],
            "action": action, "payload": payload or {},
        }, timeout=120)
        if r.status_code == 503:
            wait = 5 * 2 ** attempt
            print(f"  Aurora resuming, retry in {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("max retries exceeded")


# ── forecast rows ────────────────────────────────────────────────────────
# date_from keeps this pull small (a few real days + the forecast window)
# instead of re-downloading the full multi-thousand-row history just to
# reach the forecast tail.
date_from = (date.today() - timedelta(days=3)).isoformat()
print(f"Fetching forecast rows (date_from={date_from})...")
offset, forecast_rows = 0, []
while True:
    data = api_call("evaluate-heat-risk", {
        "project_id": PROJECT_ID, "include_forecast": True,
        "date_from": date_from, "limit": PAGE_SIZE, "offset": offset,
    })
    batch = data.get("metrics", [])
    forecast_rows.extend([r for r in batch if r.get("data_source") == "forecast"])
    print(f"  offset={offset}: {len(batch)} rows (total={data.get('total_rows', 0)})")
    if len(batch) < PAGE_SIZE:
        break
    offset += PAGE_SIZE

with open(os.path.join(BASE, "..", "boston_forecast.json"), "w") as f:
    json.dump(forecast_rows, f, separators=(",", ":"))
print(f"  boston_forecast.json — {len(forecast_rows)} forecast-source rows")

# ── air quality ──────────────────────────────────────────────────────────
print("Fetching air quality data...")
offset, aq_rows = 0, []
while True:
    data = api_call("get-air-quality-data", {
        "project_id": PROJECT_ID, "limit": PAGE_SIZE, "offset": offset,
    })
    batch = data.get("air_quality", [])
    aq_rows.extend(batch)
    print(f"  offset={offset}: {len(batch)} rows")
    if len(batch) < PAGE_SIZE:
        break
    offset += PAGE_SIZE

with open(os.path.join(BASE, "..", "boston_air_quality.json"), "w") as f:
    json.dump(aq_rows, f, separators=(",", ":"))
print(f"  boston_air_quality.json — {len(aq_rows)} rows")
print("Done.")
