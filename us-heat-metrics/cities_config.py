"""
cities_config.py — shared city registry for the US 7-city raw-metrics dashboard.

Each city has one or more "sub_projects" — most cities are backed by a single
API project, but NYC's 5 boroughs (2,324 tracts) exceed the API's 1,500-feature
per-new-project limit, so it's split into two API projects whose AOI/heat/vuln
data get merged together before scoring. process_data.py and daily_update.py
both import this so there is a single place to add/adjust a city.
"""

CITIES = {
    "fresno": {
        "label": "Fresno, CA",
        "sub_projects": [
            {
                "project_id": "fresno-2026",
                "aoi_file":   "../Cities_USA/aoi/fresno_tract_aoi.geojson",
                "heat_cache": "../fresno_heat_metrics.json",
                "vuln_cache": "../fresno_vulnerability.json",
            },
        ],
        "map_center": [36.75, -119.77],
        "map_zoom":   9,
    },
    "phoenix": {
        "label": "Phoenix, AZ",
        "sub_projects": [
            {
                "project_id": "phoenix-2026",
                "aoi_file":   "../Cities_USA/aoi/phoenix_tract_aoi.geojson",
                "heat_cache": "../phoenix_heat_metrics.json",
                "vuln_cache": "../phoenix_vulnerability.json",
            },
        ],
        "map_center": [33.45, -112.2],
        "map_zoom":   9,
    },
    "miami": {
        "label": "Miami, FL",
        "sub_projects": [
            {
                "project_id": "miami-2026",
                "aoi_file":   "../Cities_USA/aoi/miami_tract_aoi.geojson",
                "heat_cache": "../miami_heat_metrics.json",
                "vuln_cache": "../miami_vulnerability.json",
            },
        ],
        "map_center": [25.77, -80.3],
        "map_zoom":   10,
    },
    "chicago": {
        "label": "Chicago, IL",
        "sub_projects": [
            {
                "project_id": "chicago-2026",
                "aoi_file":   "../Cities_USA/aoi/chicago_tract_aoi.geojson",
                "heat_cache": "../chicago_heat_metrics.json",
                "vuln_cache": "../chicago_vulnerability.json",
            },
        ],
        "map_center": [41.85, -87.7],
        "map_zoom":   9,
    },
    "boston": {
        "label": "Boston / Cambridge, MA",
        "sub_projects": [
            {
                "project_id": "boston-cambridge-2026",
                "aoi_file":   "../Cities_USA/aoi/boston_tract_aoi.geojson",
                "heat_cache": "../boston_heat_metrics.json",
                "vuln_cache": "../boston_vulnerability.json",
            },
        ],
        "map_center": [42.38, -71.15],
        "map_zoom":   10,
    },
    "twincities": {
        "label": "Minneapolis / St Paul, MN",
        "sub_projects": [
            {
                "project_id": "twin-cities-2026",
                "aoi_file":   "../Cities_USA/aoi/twincities_tract_aoi.geojson",
                "heat_cache": "../twincities_heat_metrics.json",
                "vuln_cache": "../twincities_vulnerability.json",
            },
        ],
        "map_center": [44.97, -93.2],
        "map_zoom":   10,
    },
    "nyc": {
        "label": "New York, NY",
        "sub_projects": [
            {
                "project_id": "nyc-manhattan-brooklyn-2026",
                "aoi_file":   "../Cities_USA/aoi/nyc_a_manhattan_brooklyn_aoi.geojson",
                "heat_cache": "../nyc_a_heat_metrics.json",
                "vuln_cache": "../nyc_a_vulnerability.json",
            },
            {
                "project_id": "nyc-queens-bronx-si-2026",
                "aoi_file":   "../Cities_USA/aoi/nyc_b_queens_bronx_si_aoi.geojson",
                "heat_cache": "../nyc_b_heat_metrics.json",
                "vuln_cache": "../nyc_b_vulnerability.json",
            },
        ],
        "map_center": [40.72, -73.95],
        "map_zoom":   10,
    },
}

# Tab display order (matches the order requested)
CITY_ORDER = ["phoenix", "fresno", "miami", "chicago", "boston", "twincities", "nyc"]
