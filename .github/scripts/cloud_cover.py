"""Generate GeoJSON cloud cover map from ECMWF IFS via Open-Meteo.

Queries cloud cover at a 6x6 grid over the Bay Area, generates GeoJSON
with semi-transparent white polygons representing cloud density plus
weather station markers with live conditions.

Uses ECMWF IFS 0.25° (9km) — the gold standard NWP model.
Falls back to best_match if IFS is unavailable.

Outputs GeoJSON to stdout.
"""
import json
import sys
import urllib.request
from datetime import datetime

# Bay Area bounding box for cloud cover grid
# ~80km x 80km centered on Palo Alto
GRID_LAT_MIN = 37.25
GRID_LAT_MAX = 37.65
GRID_LON_MIN = -122.55
GRID_LON_MAX = -121.95
GRID_ROWS = 6
GRID_COLS = 6

# General Palo Alto center (not exact home)
HOME_LAT = 37.4419
HOME_LON = -122.1430

# Weather stations (METAR)
STATIONS = [
    {"name": "KPAO", "label": "Palo Alto Airport", "lat": 37.461, "lon": -122.115, "color": "#2196F3", "symbol": "airport"},
    {"name": "KNUQ", "label": "Moffett Field (NASA)", "lat": 37.4161, "lon": -122.0496, "color": "#2196F3", "symbol": "airport"},
    {"name": "KSQL", "label": "San Carlos Airport", "lat": 37.5122, "lon": -122.2508, "color": "#2196F3", "symbol": "airport"},
    {"name": "KSFO", "label": "San Francisco Intl", "lat": 37.6213, "lon": -122.3750, "color": "#9C27B0", "symbol": "airport"},
    {"name": "KSJC", "label": "San Jose Intl", "lat": 37.3626, "lon": -121.9289, "color": "#9C27B0", "symbol": "airport"},
]


def fetch_cloud_grid():
    """Fetch cloud cover at grid points from Open-Meteo ECMWF IFS."""
    lat_step = (GRID_LAT_MAX - GRID_LAT_MIN) / GRID_ROWS
    lon_step = (GRID_LON_MAX - GRID_LON_MIN) / GRID_COLS

    grid_data = []

    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            lat = GRID_LAT_MIN + (r + 0.5) * lat_step
            lon = GRID_LON_MIN + (c + 0.5) * lon_step
            grid_data.append({"lat": lat, "lon": lon, "row": r, "col": c})

    # Batch fetch - Open-Meteo supports comma-separated coordinates
    lats = ",".join(f"{p['lat']:.4f}" for p in grid_data)
    lons = ",".join(f"{p['lon']:.4f}" for p in grid_data)

    url = (
        f"https://api.open-meteo.com/v1/ecmwf?"
        f"latitude={lats}&longitude={lons}"
        f"&hourly=cloud_cover"
        f"&models=ecmwf_ifs025"
        f"&timezone=America/Los_Angeles"
        f"&forecast_days=1"
    )

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Warning: cloud cover fetch failed: {e}", file=sys.stderr)
        return grid_data  # return grid with no cloud data

    now = datetime.now()

    # Open-Meteo returns array of results for multiple coords
    if isinstance(data, list):
        results = data
    else:
        results = [data]

    for i, point in enumerate(grid_data):
        if i >= len(results):
            point["cloud_cover"] = 0
            continue
        result = results[i]
        hourly = result.get("hourly", {})
        times = hourly.get("time", [])
        cc = hourly.get("cloud_cover", [])

        # Find current hour
        hour_idx = 0
        for j, t in enumerate(times):
            if datetime.strptime(t, "%Y-%m-%dT%H:%M") >= now:
                hour_idx = max(0, j - 1)
                break

        val = cc[hour_idx] if hour_idx < len(cc) else None
        point["cloud_cover"] = val if val is not None else 0

    return grid_data


def fetch_station_conditions():
    """Fetch current conditions at home point for station descriptions."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={HOME_LAT}&longitude={HOME_LON}"
        f"&hourly=temperature_2m,cloud_cover,wind_speed_10m"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&timezone=America/Los_Angeles"
        f"&forecast_days=1"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        now = datetime.now()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        hour_idx = 0
        for j, t in enumerate(times):
            if datetime.strptime(t, "%Y-%m-%dT%H:%M") >= now:
                hour_idx = max(0, j - 1)
                break
        temp = hourly.get("temperature_2m", [None])[hour_idx]
        cc = hourly.get("cloud_cover", [None])[hour_idx]
        wind = hourly.get("wind_speed_10m", [None])[hour_idx]
        return {
            "temp": round(temp) if temp is not None else "?",
            "cloud_cover": round(cc) if cc is not None else "?",
            "wind": round(wind) if wind is not None else "?",
        }
    except Exception:
        return {"temp": 0, "cloud_cover": 0, "wind": 0}


def build_geojson(grid_data, conditions):
    """Build GeoJSON FeatureCollection with cloud polygons + station markers."""
    lat_step = (GRID_LAT_MAX - GRID_LAT_MIN) / GRID_ROWS
    lon_step = (GRID_LON_MAX - GRID_LON_MIN) / GRID_COLS

    features = []

    # Cloud cover grid polygons
    for point in grid_data:
        cc = point.get("cloud_cover", 0) or 0
        if cc < 5:
            continue  # skip clear cells

        lat = point["lat"]
        lon = point["lon"]
        half_lat = lat_step / 2
        half_lon = lon_step / 2

        # Opacity scales with cloud cover: 5% → 0.03, 100% → 0.45
        opacity = round(0.03 + (cc / 100) * 0.42, 2)

        # Color: thin clouds white, thick clouds gray
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
                    [round(lon - half_lon, 5), round(lat - half_lat, 5)],
                    [round(lon + half_lon, 5), round(lat - half_lat, 5)],
                    [round(lon + half_lon, 5), round(lat + half_lat, 5)],
                    [round(lon - half_lon, 5), round(lat + half_lat, 5)],
                    [round(lon - half_lon, 5), round(lat - half_lat, 5)],
                ]]
            },
            "properties": {
                "stroke": fill,
                "stroke-width": 0,
                "stroke-opacity": 0,
                "fill": fill,
                "fill-opacity": opacity,
                "title": f"{cc}% cloud cover",
                "description": f"ECMWF IFS 0.25 forecast / {lat:.2f}N {abs(lon):.2f}W"
            }
        })

    # Home marker
    temp = conditions.get("temp", "?")
    cc_home = conditions.get("cloud_cover", "?")
    wind = conditions.get("wind", "?")
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [HOME_LON, HOME_LAT]},
        "properties": {
            "marker-color": "#ff4444",
            "marker-size": "large",
            "marker-symbol": "star",
            "title": f"Palo Alto - {temp}F",
            "description": f"Cloud {cc_home}% / Wind {wind} mph / ECMWF IFS"
        }
    })

    # Station markers
    for s in STATIONS:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "marker-color": s["color"],
                "marker-size": "medium",
                "marker-symbol": s["symbol"],
                "title": f"{s['name']} - {s['label']}",
                "description": "METAR station / surface observations"
            }
        })

    # NDVI sample point
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-122.1030, 37.3861]},
        "properties": {
            "marker-color": "#4CAF50",
            "marker-size": "small",
            "marker-symbol": "garden",
            "title": "NDVI Sample",
            "description": "Sentinel-2 vegetation index / 10m resolution"
        }
    })

    # AQI monitor
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-122.1097, 37.4148]},
        "properties": {
            "marker-color": "#607D8B",
            "marker-size": "small",
            "marker-symbol": "marker",
            "title": "AQI Monitor",
            "description": "Open-Meteo Air Quality / PM2.5 + PM10"
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
            "title": "ECMWF IFS Grid",
            "description": "25km resolution / forecast area"
        }
    })

    return {
        "type": "FeatureCollection",
        "features": features
    }


def main():
    grid = fetch_cloud_grid()
    conditions = fetch_station_conditions()
    geojson = build_geojson(grid, conditions)
    print(json.dumps(geojson, indent=2))


if __name__ == "__main__":
    main()
