"""
Stanford Met Tower — Current Conditions

Fetches latest observation from stanford.westernweathergroup.com CSV export.
Returns JSON with current conditions + WMO weather_code for gist icons.

Usage:
    python3 .github/scripts/stanford_weather.py
"""

import base64
import csv
import io
import json
import sys
import urllib.request

STANFORD_CSV_URL = "https://stanford.westernweathergroup.com/reports/export/csv"


def fetch_current():
    """Fetch latest Stanford Met Tower observation."""
    params = {
        "Stations": ["STU"],
        "Groups": [],
        "Fields": [
            "Temp", "RH", "DewPoint", "WindDir", "WindSpeed", "WindMax",
            "SolarRad", "PressureMB", "AQI", "AQIstatus",
            "Precip", "PrecipDay", "TempMinDay", "TempMaxDay",
        ],
        "Deltas": [],
        "Interval": 60,
        "Type": "Tabular",
        "DateRange": {
            "$type": "WesternWeatherGroup.Last48HoursReportDateRange, WesternWeatherGroup.Core"
        },
        "DateDescription": "Last 48 Hours",
    }
    encoded = base64.b64encode(json.dumps(params).encode()).decode()
    url = f"{STANFORD_CSV_URL}?data={encoded}"

    req = urllib.request.Request(url, headers={"User-Agent": "atlas-gist/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return None

    # First row is the most recent observation
    row = rows[0]

    def safe_float(key):
        try:
            return float(row.get(key, "").strip())
        except (ValueError, TypeError, AttributeError):
            return None

    temp_f = safe_float("Temp (°F)")
    rh = safe_float("RH (%)")
    dew_f = safe_float("Dew Pt (°F)")
    wind_spd = safe_float("Wind Spd (mph)")
    wind_gust = safe_float("Wind Gust (mph)")
    solar = safe_float("Solar Rad (W/m2)")
    pressure = safe_float("Pressure (mb)")
    precip = safe_float("Latest Rain (In)")
    precip_day = safe_float("Daily Rain (In)")
    daily_hi = safe_float("Daily Max Temp (°F)")
    daily_lo = safe_float("Daily Min Temp (°F)")

    # Derive WMO weather_code from observations
    weather_code = derive_weather_code(temp_f, dew_f, rh, solar, precip, wind_spd)

    return {
        "temp_f": temp_f,
        "humidity": rh,
        "dew_point_f": dew_f,
        "wind_mph": wind_spd,
        "wind_gust_mph": wind_gust,
        "solar_wm2": solar,
        "pressure_mb": pressure,
        "precip_in": precip,
        "precip_day_in": precip_day,
        "daily_high_f": daily_hi,
        "daily_low_f": daily_lo,
        "weather_code": weather_code,
        "source": "stanford-met-tower",
        "obs_time": f"{row.get('Date', '')} {row.get('Time', '')}".strip(),
    }


def derive_weather_code(temp_f, dew_f, rh, solar, precip, wind_mph):
    """Derive WMO weather code from Stanford observations.

    WMO codes used by Open-Meteo:
      0=clear, 1=mainly clear, 2=partly cloudy, 3=overcast,
      45=fog, 51/53/55=drizzle, 61/63/65=rain
    """
    # Rain check
    if precip is not None and precip > 0:
        if precip > 0.1:
            return 63  # moderate rain
        return 61  # slight rain

    # Fog check: RH very high + temp near dew point
    if rh is not None and rh >= 95 and temp_f is not None and dew_f is not None:
        if abs(temp_f - dew_f) < 3:
            return 45  # fog

    # Cloud cover from solar radiation
    if solar is not None:
        from datetime import datetime
        now = datetime.now()
        hour = now.hour + now.minute / 60

        # Approximate clear-sky solar for Palo Alto by hour
        # Peak ~950 W/m2 at solar noon (~12:30 PST in late Feb)
        # Simple cosine model for daytime hours
        if hour < 6.5 or hour > 18.5:
            # Nighttime — can't determine clouds from solar
            # Use humidity as proxy
            if rh is not None and rh >= 90:
                return 45  # foggy
            if rh is not None and rh >= 75:
                return 3   # overcast
            return 0  # clear night

        # Daytime: estimate clear-sky irradiance
        solar_noon = 12.5  # approximate solar noon PST
        hour_angle = abs(hour - solar_noon)
        if hour_angle > 6:
            clear_sky = 50  # very low sun
        else:
            # Cosine model: peak 950 at noon, 0 at ±6h
            import math
            clear_sky = max(50, 950 * math.cos(math.radians(hour_angle * 15)))

        if clear_sky < 50:
            # Sun too low, can't reliably estimate
            return 1 if (rh and rh < 60) else 3

        cloud_fraction = 1.0 - (solar / clear_sky)
        cloud_fraction = max(0, min(1, cloud_fraction))

        if cloud_fraction < 0.1:
            return 0   # clear sky
        elif cloud_fraction < 0.3:
            return 1   # mainly clear
        elif cloud_fraction < 0.6:
            return 2   # partly cloudy
        else:
            return 3   # overcast

    # Fallback: use humidity
    if rh is not None:
        if rh >= 90:
            return 3
        if rh >= 70:
            return 2
        return 0

    return 0


if __name__ == "__main__":
    try:
        data = fetch_current()
        if data:
            print(json.dumps(data))
        else:
            print("{}")
    except Exception as e:
        print("{}", file=sys.stdout)
        print(f"Stanford fetch error: {e}", file=sys.stderr)
