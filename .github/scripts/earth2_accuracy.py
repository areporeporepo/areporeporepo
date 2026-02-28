"""
Earth-2 Atlas Accuracy Tracker

Compares yesterday's Atlas predictions against actual observations.
Ground truth: Stanford Met Tower (~2 mi from home, 15-min updates).

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

# Ground truth: Stanford Met Tower (~2 mi) — 15-min updates, CSV export
STANFORD_CSV_URL = "https://stanford.westernweathergroup.com/reports/export/csv"


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


def fetch_stanford_actual(date_str: str) -> dict:
    """Fetch actual observations from Stanford Met Tower via CSV export.

    Uses Last48Hours endpoint which always covers yesterday.
    Includes solar radiation as a cloud cover proxy.
    """
    import base64
    import csv
    import io
    import urllib.request

    params = {
        "Stations": ["STU"],
        "Groups": [],
        "Fields": [
            "Temp", "RH", "WindSpeed", "WindMax", "SolarRad",
            "PressureMB", "TempMinDay", "TempMaxDay",
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

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "atlas-accuracy/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8-sig")  # strip BOM

        reader = csv.DictReader(io.StringIO(text))
        temps_f = []
        winds_mph = []
        gusts_mph = []
        solar_rads = []
        daily_hi = None
        daily_lo = None

        # Parse date format: "2/26/26" → "2026-02-26"
        target_parts = date_str.split("-")  # ["2026", "02", "26"]
        target_short = f"{int(target_parts[1])}/{int(target_parts[2])}/{target_parts[0][2:]}"

        for row in reader:
            if row.get("Date") != target_short:
                continue
            try:
                temp = float(row.get("Temp (°F)", "").strip())
                temps_f.append(temp)
            except (ValueError, TypeError):
                pass
            try:
                wind = float(row.get("Wind Spd (mph)", "").strip())
                winds_mph.append(wind)
            except (ValueError, TypeError):
                pass
            try:
                gust = float(row.get("Wind Gust (mph)", "").strip())
                gusts_mph.append(gust)
            except (ValueError, TypeError):
                pass
            try:
                solar = float(row.get("Solar Rad (W/m2)", "").strip())
                solar_rads.append(solar)
            except (ValueError, TypeError):
                pass
            # Daily min/max are running values — take the last row's values
            try:
                daily_hi = float(row.get("Daily Max Temp (°F)", "").strip())
            except (ValueError, TypeError):
                pass
            try:
                daily_lo = float(row.get("Daily Min Temp (°F)", "").strip())
            except (ValueError, TypeError):
                pass

        if not temps_f:
            print(f"No Stanford data for {date_str}", file=sys.stderr)
            return {}

        # Cloud cover proxy from solar radiation
        # Peak clear-sky solar ~900-1000 W/m2 at noon in Palo Alto
        # Only use daytime readings (solar > 0) for cloud estimate
        daytime_solar = [s for s in solar_rads if s > 10]
        cloud_pct = None
        if daytime_solar:
            max_solar = max(daytime_solar)
            # Rough cloud fraction: 1 - (observed / clear-sky max)
            clear_sky = 950  # approximate clear-sky peak for this latitude
            cloud_pct = round(max(0, min(100, (1 - max_solar / clear_sky) * 100)), 1)

        return {
            "date": date_str,
            "source": "stanford-met-tower",
            "station": "STU",
            "obs_count": len(temps_f),
            "temp_high_f": daily_hi or max(temps_f),
            "temp_low_f": daily_lo or min(temps_f),
            "wind_max_mph": max(gusts_mph) if gusts_mph else (max(winds_mph) if winds_mph else None),
            "solar_max_wm2": max(solar_rads) if solar_rads else None,
            "cloud_pct_est": cloud_pct,
        }
    except Exception as e:
        print(f"Stanford fetch failed: {e}", file=sys.stderr)
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

    # Fetch actual observations from Stanford Met Tower
    actual = fetch_stanford_actual(yesterday)
    if not actual or actual.get("temp_high_f") is None:
        print("Stanford data unavailable, skipping")
        return
    print(f"Ground truth: {actual.get('source')} ({actual.get('obs_count', '?')} obs)")
    if actual.get("cloud_pct_est") is not None:
        print(f"Cloud cover estimate: {actual['cloud_pct_est']}%")

    # Get Atlas prediction for yesterday
    atlas_pred = get_atlas_prediction(yesterday)

    # Read existing accuracy log
    accuracy_log = []
    if FORECAST_GIST_ID:
        raw = read_gist_file(FORECAST_GIST_ID, "accuracy_log.json")
        if raw:
            try:
                parsed = json.loads(raw)
                # Handle both wrapped {"log": [...]} and raw list formats
                if isinstance(parsed, dict):
                    accuracy_log = parsed.get("log", [])
                elif isinstance(parsed, list):
                    accuracy_log = parsed
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
