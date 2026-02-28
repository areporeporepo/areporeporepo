"""Generate GeoJSON cloud cover map from Atlas forecast + Stanford stations.

Reads Atlas forecast data (from E2_DATA env var) for cloud cover,
scrapes live Stanford weather station data for station markers.

Atlas provides 0.25° resolution cloud cover at the Palo Alto grid point.
Stanford weather stations update every 15 minutes.

Outputs GeoJSON to stdout.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta

# Bay Area bounding box for display
GRID_LAT_MIN = 37.25
GRID_LAT_MAX = 37.65
GRID_LON_MIN = -122.55
GRID_LON_MAX = -121.95

# General Palo Alto center (not exact home)
HOME_LAT = 37.4419
HOME_LON = -122.1430


def get_atlas_cloud_cover():
    """Get current cloud cover from Atlas forecast (E2_DATA env var)."""
    e2_raw = os.environ.get("E2_DATA", "{}")
    try:
        atlas = json.loads(e2_raw)
    except json.JSONDecodeError:
        return None

    init_time = atlas.get("init_time", "")
    hourly = atlas.get("hourly_6h", [])
    if not init_time or not hourly:
        return None

    try:
        init_dt = datetime.fromisoformat(init_time)
    except (ValueError, TypeError):
        return None

    now = datetime.now()

    # Find the closest 6h step to now
    best_step = None
    best_diff = float("inf")
    for step in hourly:
        step_dt = init_dt + timedelta(hours=step["lead_hours"])
        diff = abs((step_dt - now).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_step = step

    if best_step is None:
        return None

    grid_lat = atlas.get("location", {}).get("grid_lat", HOME_LAT)
    grid_lon_360 = atlas.get("location", {}).get("grid_lon", 360 + HOME_LON)
    # Convert 0-360 back to -180..180
    grid_lon = grid_lon_360 - 360 if grid_lon_360 > 180 else grid_lon_360

    return {
        "cloud_pct": best_step.get("cloud_pct", 0) or 0,
        "weather_code": best_step.get("weather_code", 0),
        "temp_f": best_step.get("temp_f"),
        "grid_lat": grid_lat,
        "grid_lon": grid_lon,
        "model": atlas.get("model", "atlas-crps"),
        "init_time": init_time,
    }


def fetch_stanford_weather():
    """Scrape live data from Stanford weather stations (updates every 15 min)."""
    url = "https://stanford.westernweathergroup.com/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Warning: Stanford weather fetch failed: {e}", file=sys.stderr)
        return None

    met_idx = html.find("Met Tower")
    rwc_idx = html.find("Redwood City")
    if met_idx < 0:
        return None

    met_html = html[met_idx:rwc_idx] if rwc_idx > met_idx else html[met_idx:]
    rwc_html = html[rwc_idx:] if rwc_idx > 0 else ""

    def parse_rows(section):
        d = {}
        for label, val in re.findall(r'<th>([^<]+)</th>\s*<td[^>]*>\s*([\d.]+)', section):
            d[label.strip()] = val
        return d

    met = parse_rows(met_html)
    rwc = parse_rows(rwc_html) if rwc_html else {}

    ts_match = re.search(r'(\d+/\d+/\d+\s+\d+:\d+\s*[AP]M)', html)
    timestamp = ts_match.group(1) if ts_match else ""

    return {
        "met_tower": {
            "temp": met.get("Temp", "?"),
            "rh": met.get("RH", "?"),
            "wind": met.get("Wind Spd", "?"),
            "gust": met.get("Wind Gust", "?"),
            "aqi": met.get("NowCast AQI Value", "?"),
            "precip_24h": met.get("Precip 24Hr", "?"),
            "season_precip": met.get("Season Precip", "?"),
        },
        "redwood_city": {
            "temp": rwc.get("Temp", "?"),
            "rh": rwc.get("RH", "?"),
            "wind": rwc.get("Wind Spd", "?"),
            "gust": rwc.get("Wind Gust", "?"),
            "aqi": rwc.get("NowCast AQI Value", "?"),
            "precip_24h": rwc.get("Precip 24Hr", "?"),
            "season_precip": rwc.get("Season Precip", "?"),
        },
        "timestamp": timestamp,
    }


def build_geojson(atlas_cloud, stanford):
    """Build GeoJSON FeatureCollection."""
    features = []

    # Atlas cloud cover — single polygon covering the forecast area
    if atlas_cloud:
        cc = atlas_cloud["cloud_pct"]
        if cc >= 5:
            opacity = round(0.03 + (cc / 100) * 0.42, 2)
            if cc >= 80:
                fill = "#9E9E9E"
            elif cc >= 50:
                fill = "#BDBDBD"
            else:
                fill = "#E0E0E0"
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [GRID_LON_MIN, GRID_LAT_MIN],
                        [GRID_LON_MAX, GRID_LAT_MIN],
                        [GRID_LON_MAX, GRID_LAT_MAX],
                        [GRID_LON_MIN, GRID_LAT_MAX],
                        [GRID_LON_MIN, GRID_LAT_MIN],
                    ]]
                },
                "properties": {
                    "stroke": fill,
                    "stroke-width": 0,
                    "stroke-opacity": 0,
                    "fill": fill,
                    "fill-opacity": opacity,
                    "title": f"{cc}% cloud cover",
                    "description": (
                        f"Atlas-CRPS forecast / "
                        f"{atlas_cloud['grid_lat']:.2f}N {abs(atlas_cloud['grid_lon']):.2f}W"
                    )
                }
            })

    # Stanford Met Tower
    if stanford:
        mt = stanford["met_tower"]
        ts = stanford["timestamp"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.1720, 37.4275]},
            "properties": {
                "marker-color": "#8B0000",
                "marker-size": "large",
                "marker-symbol": "college",
                "title": f"Stanford Met Tower - {mt['temp']}F",
                "description": (
                    f"RH {mt['rh']}% / Wind {mt['wind']} mph "
                    f"(gust {mt['gust']}) / AQI {mt['aqi']} / "
                    f"Rain 24h {mt['precip_24h']}in / "
                    f"Season {mt['season_precip']}in / {ts}"
                )
            }
        })

        rc = stanford["redwood_city"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.2150, 37.4850]},
            "properties": {
                "marker-color": "#8B0000",
                "marker-size": "medium",
                "marker-symbol": "college",
                "title": f"Stanford Redwood City - {rc['temp']}F",
                "description": (
                    f"RH {rc['rh']}% / Wind {rc['wind']} mph "
                    f"(gust {rc['gust']}) / AQI {rc['aqi']} / "
                    f"Rain 24h {rc['precip_24h']}in / "
                    f"Season {rc['season_precip']}in / {ts}"
                )
            }
        })

    # Palo Alto marker
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [HOME_LON, HOME_LAT]},
        "properties": {
            "marker-color": "#ff4444",
            "marker-size": "large",
            "marker-symbol": "star",
            "title": "Palo Alto",
            "description": (
                f"Atlas-CRPS forecast point"
                + (f" / {atlas_cloud['cloud_pct']}% cloud" if atlas_cloud else "")
            )
        }
    })

    # Forecast grid outline
    features.append({
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [GRID_LON_MIN, GRID_LAT_MIN],
                [GRID_LON_MAX, GRID_LAT_MIN],
                [GRID_LON_MAX, GRID_LAT_MAX],
                [GRID_LON_MIN, GRID_LAT_MAX],
                [GRID_LON_MIN, GRID_LAT_MIN],
            ]]
        },
        "properties": {
            "stroke": "#ff4444",
            "stroke-width": 1,
            "stroke-opacity": 0.3,
            "fill": "#ff4444",
            "fill-opacity": 0.02,
            "title": "Atlas Forecast Grid",
            "description": "0.25° resolution / forecast area"
        }
    })

    return {"type": "FeatureCollection", "features": features}


def main():
    atlas_cloud = get_atlas_cloud_cover()
    stanford = fetch_stanford_weather()
    geojson = build_geojson(atlas_cloud, stanford)
    print(json.dumps(geojson, indent=2))


if __name__ == "__main__":
    main()
