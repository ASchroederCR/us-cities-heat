"""
daily_update.py — incremental daily pull for all US cities, then rescore all.

Usage:
    py daily_update.py                  # incremental update, all cities with a project
    py daily_update.py fresno phoenix   # only these cities
    py daily_update.py --full           # full re-download for every targeted city
"""

import json
import os
import sys
import time
import logging
from datetime import date, datetime, timedelta

import requests

from cities_config import CITIES, CITY_ORDER

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(BASE_DIR, "credentials.json")
LOG_FILE  = os.path.join(BASE_DIR, "update.log")

PAGE_SIZE   = 500
MAX_RETRIES = 6
BASE_DELAY  = 5


def _load_credentials():
    username = os.environ.get("HEAT_API_USERNAME")
    key      = os.environ.get("HEAT_API_KEY")
    api_url  = os.environ.get("HEAT_API_URL")
    if username and key and api_url:
        return username, key, api_url
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return creds["username"], creds["key"], creds["api_url"]
    raise RuntimeError(
        "API credentials not found. Set HEAT_API_USERNAME, HEAT_API_KEY, HEAT_API_URL "
        "environment variables, or copy credentials.example.json to credentials.json."
    )


USERNAME, API_KEY, API_URL = _load_credentials()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def api_call(action, payload=None):
    body = {"username": USERNAME, "key": API_KEY, "action": action, "payload": payload or {}}
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(API_URL, json=body, timeout=120)
        except requests.RequestException as exc:
            log.warning("Network error attempt %d: %s", attempt + 1, exc)
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(BASE_DELAY * (2 ** attempt))
            continue
        if resp.status_code == 503:
            wait = BASE_DELAY * (2 ** attempt)
            log.info("Aurora resuming (503) — retry in %ds (%d/%d)", wait, attempt + 1, MAX_RETRIES)
            time.sleep(wait)
            continue
        if resp.status_code not in (200, 202):
            log.error("API error %d: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Max retries exceeded")


def fetch_all_metrics(project_id, date_from=None):
    offset, rows = 0, []
    while True:
        payload = {"project_id": project_id, "limit": PAGE_SIZE, "offset": offset}
        if date_from:
            payload["date_from"] = date_from
        data = api_call("evaluate-heat-risk", payload)
        batch = data.get("metrics", [])
        rows.extend(batch)
        log.info("  [%s] offset=%d: %d rows (total=%d)", project_id, offset, len(batch), data.get("total_rows", 0))
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def update_subproject(city_key, sp, last_run, full_reload):
    heat_cache = os.path.join(BASE_DIR, sp["heat_cache"])
    project_id = sp["project_id"]

    date_from = None
    if not full_reload and os.path.exists(last_run):
        with open(last_run) as f:
            meta = json.load(f)
        last_date = meta.get("data_date_range", [None, None])[1]
        if last_date:
            date_from = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    log.info("[%s/%s] fetching from %s", city_key, project_id, date_from or "(all)")
    new_rows = fetch_all_metrics(project_id, date_from=date_from)
    log.info("[%s/%s] fetched %d new rows", city_key, project_id, len(new_rows))

    if not new_rows and not full_reload:
        log.info("[%s/%s] already up to date", city_key, project_id)
        return False

    if full_reload or not os.path.exists(heat_cache):
        all_rows = new_rows
    else:
        with open(heat_cache) as f:
            existing = json.load(f)
        new_keys = {(r["name"], r["date"]) for r in new_rows}
        merged = [r for r in existing if (r["name"], r["date"]) not in new_keys]
        all_rows = merged + new_rows
        log.info("[%s/%s] merged: %d existing + %d new = %d total", city_key, project_id, len(merged), len(new_rows), len(all_rows))

    with open(heat_cache, "w") as f:
        json.dump(all_rows, f, separators=(",", ":"))
    log.info("[%s/%s] cache updated (%d rows)", city_key, project_id, len(all_rows))
    return True


def ensure_vulnerability_cache(city_key, sp):
    vuln_cache = os.path.join(BASE_DIR, sp["vuln_cache"])
    if os.path.exists(vuln_cache):
        return
    log.info("[%s/%s] fetching vulnerability data", city_key, sp["project_id"])
    data = api_call("get-vulnerability-data", {"project_id": sp["project_id"]})
    rows = data.get("vulnerability", [])
    if not rows:
        log.warning("[%s/%s] vulnerability data not ready yet", city_key, sp["project_id"])
        return
    with open(vuln_cache, "w") as f:
        json.dump(rows, f, separators=(",", ":"))
    log.info("[%s/%s] vulnerability cache written (%d rows)", city_key, sp["project_id"], len(rows))


def main():
    args = [a for a in sys.argv[1:] if a != "--full"]
    full_reload = "--full" in sys.argv
    keys = args if args else CITY_ORDER

    log.info("=== daily_update.py start (mode=%s, cities=%s) ===",
              "full" if full_reload else "incremental", ",".join(keys))

    any_updated = False
    for key in keys:
        if key not in CITIES:
            log.warning("unknown city key: %s", key)
            continue
        cfg = CITIES[key]
        last_run = os.path.join(BASE_DIR, "data", key, "last_run.json")
        try:
            for sp in cfg["sub_projects"]:
                ensure_vulnerability_cache(key, sp)
                if update_subproject(key, sp, last_run, full_reload):
                    any_updated = True
        except Exception as exc:
            log.error("[%s] update failed: %s", key, exc)

    if not any_updated and not full_reload:
        log.info("No cities had new data. Skipping rescore.")
        return

    log.info("Re-running process_data.py for updated cities...")
    import subprocess
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "process_data.py")] + keys,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error("process_data.py failed:\n%s", result.stderr)
        raise RuntimeError("Scoring pipeline failed")
    log.info("process_data.py output:\n%s", result.stdout.strip())
    log.info("=== daily_update.py complete ===")


if __name__ == "__main__":
    main()
