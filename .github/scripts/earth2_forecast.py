"""
Earth-2 Atlas Forecast Reader for GitHub Actions

Reads cached Atlas forecast JSON from data gist.
Returns full forecast data (daily + 6-hourly with cloud cover) for weather gist.
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


def build_output(forecast: dict) -> dict:
    """Build output for weather-box workflow."""
    if not forecast:
        return {}

    gen = forecast.get("generated_at", "")
    age_hours = None
    stale = True
    if gen:
        try:
            gen_dt = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            age_hours = (datetime.now(gen_dt.tzinfo) - gen_dt).total_seconds() / 3600
            stale = age_hours > 12
        except (ValueError, TypeError):
            pass

    return {
        "model": forecast.get("model", "atlas-crps"),
        "model_params": forecast.get("model_params", ""),
        "init_time": forecast.get("init_time", ""),
        "generated_at": gen,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "stale": stale,
        "location": forecast.get("location", {}),
        "daily": forecast.get("daily", []),
        "hourly_6h": forecast.get("hourly_6h", []),
    }


def main():
    forecast = read_forecast_gist()
    result = build_output(forecast)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
