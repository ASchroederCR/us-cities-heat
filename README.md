# US Cities Heat

A dashboard of heat-risk and social-vulnerability metrics across 7 US metro
areas: Phoenix AZ, Fresno CA, Miami FL, Chicago IL, Boston/Cambridge MA,
Minneapolis/St Paul MN, and New York NY.

Metrics are shown at the census-tract level as raw values (no composite
index): heat index peak, heat anomaly vs. historical, extreme-heat-day %,
nighttime stress, health facility access, built fraction, tree canopy,
night lights, HDI, and population.

Data is pulled from the Heat Risk Data API, one API project per city (New
York is split across two API projects due to its tract count, merged
client-side into a single tab). Each city's data is deployed independently
as its 10-year WMO reference climatology finishes computing, so the site
may show some cities as "pending" while others are live.

This is a companion project to a separate Delhi/Kano heat-vulnerability
dashboard.

## `cambridge-heat-map/`

A standalone, light-themed, embeddable Leaflet map covering the full
Boston/Cambridge metro area (Suffolk + Middlesex counties, 591 census
tracts) — built for daily-resolution exploration with a time slider, rather
than the rolling-window tabbed view in `us-heat-metrics/`. It reuses the
same underlying `boston-cambridge-2026` API project data (no separate API
project). See `cambridge-heat-map/build_data.py` for the day-level
processing and `cambridge-heat-map/index.html` for the map itself. Deployed
at `/cambridge/` on the Pages site.

## Running `daily_update.py` locally

1. Copy `us-heat-metrics/credentials.example.json` to
   `us-heat-metrics/credentials.json` and fill in your own `api_url`,
   `username`, and `key`.
2. From `us-heat-metrics/`, run:

   ```
   py daily_update.py --full <city_key>
   ```

   or omit `--full` for an incremental update. `<city_key>` is one of:
   `fresno`, `twincities`, `boston`, `miami`, `phoenix`, `chicago`, `nyc`.

`process_data.py` expects AOI polygon files at `../Cities_USA/aoi/` relative
to `us-heat-metrics/`, which is why that folder is included at the repo
root alongside it.
