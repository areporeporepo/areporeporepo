"""
Earth-2 Atlas Forecast Reader for GitHub Actions

Reads cached Atlas forecast JSON from data gist.
Returns prediction for today + tomorrow to be displayed in weather gist.
No GPU needed — just reads pre-computed data.

Usage:
    python3 .github/scripts/earth2_forecast.py
    # Outputs JSON to stdout
"""

import json
import os
import subprocess
import sys
from datetime import datetime


def read_forecast_gist() -> dict:
    """Read Atlas forecast JSON from data gist."""
    gist_id = os.environ.get("FORECAST_GIST_ID", "")
    if not gist_id:
        return {}

    result = subprocess.run(
        ["gh", "gist", "view", gist_id, "-f", "atlas_forecast.json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Failed to read forecast gist: {result.stderr}", file=sys.stderr)
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Failed to parse forecast JSON", file=sys.stderr)
        return {}


def get_forecast_for_dates(forecast: dict) -> dict:
    """Extract today and tomorrow's forecast from cached data."""
    if not forecast or "daily" not in forecast:
        return {}

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now.replace(hour=0) + __import__("datetime").timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )

    daily = {d["date"]: d for d in forecast.get("daily", [])}

    result = {
        "model": forecast.get("model", "atlas-crps"),
        "init_time": forecast.get("init_time", ""),
        "generated_at": forecast.get("generated_at", ""),
    }

    if today in daily:
        result["today"] = daily[today]
    if tomorrow in daily:
        result["tomorrow"] = daily[tomorrow]

    # Check staleness — forecast older than 12h is stale
    gen = forecast.get("generated_at", "")
    if gen:
        try:
            gen_dt = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            age_hours = (datetime.now(gen_dt.tzinfo) - gen_dt).total_seconds() / 3600
            result["age_hours"] = round(age_hours, 1)
            result["stale"] = age_hours > 12
        except (ValueError, TypeError):
            result["stale"] = True

    return result


def compare_with_openmeteo(atlas: dict, om_temp_high: float = None) -> dict:
    """Compare Atlas forecast with Open-Meteo for gist display."""
    comparison = {}

    tomorrow = atlas.get("tomorrow", {})
    if not tomorrow:
        return comparison

    atlas_high = tomorrow.get("temp_high_f")
    atlas_wind = tomorrow.get("wind_avg_mph")

    if atlas_high is not None and om_temp_high is not None:
        comparison["temp_delta"] = round(atlas_high - om_temp_high, 1)

    if atlas_high is not None:
        comparison["atlas_temp_f"] = atlas_high
    if atlas_wind is not None:
        comparison["atlas_wind_mph"] = atlas_wind

    return comparison


def main():
    forecast = read_forecast_gist()
    result = get_forecast_for_dates(forecast)

    # If called with Open-Meteo temp as argument, add comparison
    if len(sys.argv) > 1:
        try:
            om_high = float(sys.argv[1])
            atlas = get_forecast_for_dates(forecast)
            result["comparison"] = compare_with_openmeteo(atlas, om_high)
        except (ValueError, IndexError):
            pass

    print(json.dumps(result))


if __name__ == "__main__":
    main()
