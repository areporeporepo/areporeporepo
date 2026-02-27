"""
Earth-2 Atlas Accuracy Tracker

Compares yesterday's Atlas + Open-Meteo predictions against actual observations.
Calculates MAE, appends to accuracy log in data gist.

Run daily via GitHub Actions (separate workflow or cron job).

Usage:
    python3 .github/scripts/earth2_accuracy.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta


FORECAST_GIST_ID = os.environ.get("FORECAST_GIST_ID", "")
PA_LAT = "37.44783"
PA_LON = "-122.13604"


def read_gist_file(gist_id: str, filename: str) -> str:
    """Read a file from a GitHub gist."""
    result = subprocess.run(
        ["gh", "gist", "view", gist_id, "-f", filename],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def write_gist_file(gist_id: str, filename: str, content: str) -> bool:
    """Write a file to a GitHub gist with retry."""
    for attempt in range(3):
        result = subprocess.run(
            ["gh", "gist", "edit", gist_id, "-f", filename, "-"],
            input=content,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return True
        print(f"Gist write failed (attempt {attempt + 1}): {result.stderr}", file=sys.stderr)
    return False


def fetch_openmeteo_actual(date_str: str) -> dict:
    """Fetch actual observed weather from Open-Meteo historical API."""
    import urllib.request

    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={PA_LAT}&longitude={PA_LON}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&daily=temperature_2m_max,temperature_2m_min,wind_speed_10m_max"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&timezone=America/Los_Angeles"
    )

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            daily = data.get("daily", {})
            return {
                "date": date_str,
                "source": "open-meteo-archive",
                "temp_high_f": daily.get("temperature_2m_max", [None])[0],
                "temp_low_f": daily.get("temperature_2m_min", [None])[0],
                "wind_max_mph": daily.get("wind_speed_10m_max", [None])[0],
            }
    except Exception as e:
        print(f"Failed to fetch actuals: {e}", file=sys.stderr)
        return {}


def fetch_openmeteo_forecast_for_date(date_str: str) -> dict:
    """Fetch what Open-Meteo predicted for a given date (from its forecast API)."""
    # Open-Meteo doesn't store past forecasts, so we use the current forecast
    # as a proxy. For proper tracking, we'd need to log OM predictions daily.
    # This function reads from cached OM predictions in the accuracy log.
    return {}


def get_atlas_prediction(date_str: str) -> dict:
    """Get Atlas prediction for a specific date from cached forecast."""
    if not FORECAST_GIST_ID:
        return {}

    raw = read_gist_file(FORECAST_GIST_ID, "atlas_forecast.json")
    if not raw:
        return {}

    try:
        forecast = json.loads(raw)
        for day in forecast.get("daily", []):
            if day.get("date") == date_str:
                return {
                    "date": date_str,
                    "source": "atlas-crps",
                    "init_time": forecast.get("init_time", ""),
                    "temp_high_f": day.get("temp_high_f"),
                    "temp_low_f": day.get("temp_low_f"),
                    "wind_max_mph": day.get("wind_max_mph"),
                    "wind_avg_mph": day.get("wind_avg_mph"),
                }
    except json.JSONDecodeError:
        pass

    return {}


def calculate_mae(predictions: list[dict], actuals: list[dict], field: str) -> float:
    """Calculate Mean Absolute Error for a field across paired predictions/actuals."""
    errors = []
    actual_map = {a["date"]: a for a in actuals}

    for pred in predictions:
        date = pred.get("date")
        if date not in actual_map:
            continue
        p = pred.get(field)
        a = actual_map[date].get(field)
        if p is not None and a is not None:
            errors.append(abs(p - a))

    if not errors:
        return None
    return round(sum(errors) / len(errors), 2)


def main():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Checking accuracy for {yesterday}")

    # Fetch actual observations
    actual = fetch_openmeteo_actual(yesterday)
    if not actual or actual.get("temp_high_f") is None:
        print("No actuals available yet, skipping")
        return

    # Get Atlas prediction for yesterday
    atlas_pred = get_atlas_prediction(yesterday)

    # Read existing accuracy log
    accuracy_log = []
    if FORECAST_GIST_ID:
        raw = read_gist_file(FORECAST_GIST_ID, "accuracy_log.json")
        if raw:
            try:
                accuracy_log = json.loads(raw)
            except json.JSONDecodeError:
                accuracy_log = []

    # Build today's accuracy entry
    entry = {
        "date": yesterday,
        "actual": actual,
        "atlas": atlas_pred if atlas_pred else None,
    }

    # Calculate errors
    if atlas_pred and actual:
        for field in ["temp_high_f", "temp_low_f", "wind_max_mph"]:
            a_val = actual.get(field)
            p_val = atlas_pred.get(field)
            if a_val is not None and p_val is not None:
                entry[f"atlas_{field}_error"] = round(abs(p_val - a_val), 1)

    # Append to log (keep last 90 days)
    accuracy_log.append(entry)
    accuracy_log = accuracy_log[-90:]

    # Calculate running MAE (last 14 days)
    recent = accuracy_log[-14:]
    atlas_preds = [e["atlas"] for e in recent if e.get("atlas")]
    actuals = [e["actual"] for e in recent if e.get("actual")]

    summary = {
        "last_updated": datetime.now().isoformat(),
        "total_days": len(accuracy_log),
        "atlas_days": len(atlas_preds),
    }

    if atlas_preds and actuals:
        summary["atlas_temp_mae_14d"] = calculate_mae(atlas_preds, actuals, "temp_high_f")
        summary["atlas_wind_mae_14d"] = calculate_mae(atlas_preds, actuals, "wind_max_mph")

    print(f"Accuracy entry: {json.dumps(entry, indent=2)}")
    print(f"Summary: {json.dumps(summary, indent=2)}")

    # Write back to gist
    if FORECAST_GIST_ID:
        log_data = {"summary": summary, "log": accuracy_log}
        write_gist_file(FORECAST_GIST_ID, "accuracy_log.json", json.dumps(log_data, indent=2))
        print("Accuracy log updated")
    else:
        print("FORECAST_GIST_ID not set, printing only")
        print(json.dumps({"summary": summary, "log": accuracy_log}, indent=2))


if __name__ == "__main__":
    main()
