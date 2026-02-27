"""
Atlas Weather Forecast on Modal (A100 GPU)

Runs NVIDIA Atlas-CRPS (4.3B params) via earth2studio for 5-day forecasts.
Scheduled 4x/day after GFS cycles. Stores results in GitHub data gist.

Deploy:  modal deploy .github/scripts/atlas_modal.py
Test:    modal run .github/scripts/atlas_modal.py::run_forecast
Cost:    ~$0.09/run × 4/day × 30 days ≈ $10.80/mo (covered by $30 free credit)
"""

import json
import os
from datetime import datetime, timezone

import modal

app = modal.App("atlas-forecast")

# Persistent volume for cached model weights (17.8 GB)
volume = modal.Volume.from_name("atlas-weights", create_if_missing=True)

image = (
    modal.Image.from_registry("nvcr.io/nvidia/pytorch:24.12-py3")
    .env({"NATTEN_CUDA_ARCH": "8.0"})  # A100 sm_80, needed for NATTEN build without GPU
    # Upgrade PyTorch to 2.9+ (NATTEN 0.21.5 requires ≥2.8 at runtime)
    .run_commands("pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu126")
    .pip_install(
        "earth2studio[atlas]",
        "xarray",
        "zarr",
        "requests",
        "numpy",
    )
    .env({"HF_HOME": "/weights/hf_cache", "TORCH_HOME": "/weights/torch_cache"})
)

# Palo Alto coordinates
PA_LAT = 37.4478
PA_LON = -122.1360  # earth2studio uses 0-360 → 237.864

# Variables to extract at Palo Alto grid point
EXTRACT_VARS = ["t2m", "u10m", "v10m", "msl", "tcwv", "sp"]

# Data gist for forecast cache (set via modal secret or env)
FORECAST_GIST_ID = os.environ.get("FORECAST_GIST_ID", "")


def kelvin_to_f(k: float) -> float:
    return round((k - 273.15) * 9 / 5 + 32, 1)


def ms_to_mph(ms: float) -> float:
    return round(ms * 2.237, 1)


def pa_to_inhg(pa: float) -> float:
    return round(pa / 3386.39, 2)


def extract_palo_alto(io_backend) -> list[dict]:
    """Extract forecast data at nearest grid point to Palo Alto."""
    import numpy as np

    lats = io_backend["lat"][:]
    lons = io_backend["lon"][:]

    # earth2studio uses 0-360 longitude convention
    target_lon = 360.0 + PA_LON  # -122.14 → 237.86

    lat_idx = int(np.argmin(np.abs(lats - PA_LAT)))
    lon_idx = int(np.argmin(np.abs(lons - target_lon)))

    actual_lat = float(lats[lat_idx])
    actual_lon = float(lons[lon_idx])

    forecasts = []
    # io_backend shape: [batch, lead_time, variable, lat, lon]
    # lead_time steps are 0..nsteps, each 6h apart
    t2m_data = io_backend["t2m"][0, :, lat_idx, lon_idx] if "t2m" in io_backend else None

    # Get number of time steps from any variable
    for var in EXTRACT_VARS:
        if var in io_backend:
            nsteps = io_backend[var].shape[1]
            break
    else:
        return []

    for step in range(nsteps):
        lead_hours = step * 6
        entry = {"lead_hours": lead_hours}

        for var in EXTRACT_VARS:
            if var in io_backend:
                val = float(io_backend[var][0, step, lat_idx, lon_idx])
                entry[var] = val

        # Derived fields
        if "t2m" in entry:
            entry["temp_f"] = kelvin_to_f(entry["t2m"])
        if "u10m" in entry and "v10m" in entry:
            wind_ms = (entry["u10m"] ** 2 + entry["v10m"] ** 2) ** 0.5
            entry["wind_mph"] = ms_to_mph(wind_ms)
        if "msl" in entry:
            entry["pressure_inhg"] = pa_to_inhg(entry["msl"])

        forecasts.append(entry)

    return forecasts, actual_lat, actual_lon


def aggregate_daily(forecasts: list[dict], init_time: str) -> list[dict]:
    """Aggregate 6-hourly forecasts into daily summaries."""
    from datetime import timedelta

    init_dt = datetime.fromisoformat(init_time)
    daily = {}

    for entry in forecasts:
        lead_h = entry["lead_hours"]
        valid_dt = init_dt + timedelta(hours=lead_h)
        day_key = valid_dt.strftime("%Y-%m-%d")

        if day_key not in daily:
            daily[day_key] = {
                "date": day_key,
                "temps_f": [],
                "winds_mph": [],
                "pressures": [],
            }

        if "temp_f" in entry:
            daily[day_key]["temps_f"].append(entry["temp_f"])
        if "wind_mph" in entry:
            daily[day_key]["winds_mph"].append(entry["wind_mph"])
        if "pressure_inhg" in entry:
            daily[day_key]["pressures"].append(entry["pressure_inhg"])

    result = []
    for day_key in sorted(daily.keys()):
        d = daily[day_key]
        temps = d["temps_f"]
        winds = d["winds_mph"]
        pressures = d["pressures"]
        result.append(
            {
                "date": d["date"],
                "temp_high_f": round(max(temps), 1) if temps else None,
                "temp_low_f": round(min(temps), 1) if temps else None,
                "temp_avg_f": round(sum(temps) / len(temps), 1) if temps else None,
                "wind_avg_mph": round(sum(winds) / len(winds), 1) if winds else None,
                "wind_max_mph": round(max(winds), 1) if winds else None,
                "pressure_avg_inhg": (
                    round(sum(pressures) / len(pressures), 2) if pressures else None
                ),
            }
        )

    return result


def push_to_gist(payload: dict) -> None:
    """Push forecast JSON to GitHub data gist via REST API."""
    import requests
    import time

    gist_id = FORECAST_GIST_ID
    if not gist_id:
        print("FORECAST_GIST_ID not set, skipping gist push")
        return

    gh_token = os.environ.get("GH_TOKEN", "")
    if not gh_token:
        print("GH_TOKEN not set, skipping gist push")
        return

    forecast_json = json.dumps(payload, indent=2)

    for attempt in range(3):
        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {gh_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"files": {"atlas_forecast.json": {"content": forecast_json}}},
            timeout=15,
        )
        if resp.status_code == 200:
            print(f"Gist updated successfully (attempt {attempt + 1})")
            return
        print(f"Gist update failed (attempt {attempt + 1}): {resp.status_code} {resp.text[:200]}")
        time.sleep(5)

    print("All gist update attempts failed")


@app.function(
    gpu="A100",
    image=image,
    volumes={"/weights": volume},
    timeout=2400,
    schedule=modal.Cron("30 3,9,15,21 * * *"),  # ~3.5h after each GFS cycle
    secrets=[
        modal.Secret.from_name("atlas-secrets", required_keys=[]),
    ],
)
def run_forecast():
    """Run Atlas 5-day forecast and store results."""
    from earth2studio.data import GFS
    from earth2studio.io import ZarrBackend
    from earth2studio.models.px import Atlas
    from earth2studio.run import deterministic as run_deterministic

    print("Loading Atlas model...")
    package = Atlas.load_default_package()
    model = Atlas.load_model(package)
    volume.commit()  # persist cached weights

    print("Initializing GFS data source...")
    data = GFS()

    print("Setting up IO backend...")
    io = ZarrBackend()

    # Use previous GFS cycle that's definitely available on S3
    # GFS data takes ~3.5-4h to process, so go back one full cycle (6h) from current
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    cycle_hour = (now.hour // 6) * 6
    current_cycle = now.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
    # Use previous cycle to ensure data is available
    init_time = current_cycle - timedelta(hours=6)
    init_str = init_time.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"Running 5-day forecast from {init_str} (20 steps × 6h)...")
    nsteps = 20  # 20 × 6h = 120h = 5 days

    # Try current-6h cycle first, fall back to current-12h if not ready
    try:
        io = run_deterministic([init_str], nsteps, model, data, io)
    except FileNotFoundError:
        print(f"GFS data for {init_str} not ready, trying previous cycle...")
        init_time = current_cycle - timedelta(hours=12)
        init_str = init_time.strftime("%Y-%m-%dT%H:%M:%S")
        io = ZarrBackend()
        io = run_deterministic([init_str], nsteps, model, data, io)

    print("Extracting Palo Alto grid point...")
    forecasts, actual_lat, actual_lon = extract_palo_alto(io)
    daily = aggregate_daily(forecasts, init_str)

    payload = {
        "model": "atlas-crps",
        "model_params": "4.3B",
        "init_time": init_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "location": {
            "name": "Palo Alto, CA",
            "target_lat": PA_LAT,
            "target_lon": PA_LON,
            "grid_lat": actual_lat,
            "grid_lon": actual_lon,
        },
        "daily": daily,
        "hourly_6h": forecasts,
    }

    print(f"Forecast complete: {len(daily)} days, {len(forecasts)} timesteps")
    print(json.dumps(payload, indent=2)[:500])

    push_to_gist(payload)
    volume.commit()

    return payload
