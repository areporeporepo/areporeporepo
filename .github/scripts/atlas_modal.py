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
# Surface + upper-level humidity/temp for cloud cover estimation
EXTRACT_VARS = ["t2m", "u10m", "v10m", "msl", "tcwv", "sp", "tp"]
CLOUD_VARS = ["q850", "q700", "q500", "t850", "t700", "t500"]

# Data gist for forecast cache (set via modal secret or env)
FORECAST_GIST_ID = os.environ.get("FORECAST_GIST_ID", "")


def kelvin_to_f(k: float) -> float:
    return round((k - 273.15) * 9 / 5 + 32, 1)


def ms_to_mph(ms: float) -> float:
    return round(ms * 2.237, 1)


def pa_to_inhg(pa: float) -> float:
    return round(pa / 3386.39, 2)


def specific_to_relative_humidity(q, t_kelvin, p_hpa):
    """Convert specific humidity (kg/kg) to relative humidity (0-100%).

    Uses Tetens formula for saturation vapor pressure.
    q: specific humidity (kg/kg)
    t_kelvin: temperature (K)
    p_hpa: pressure level (hPa)
    """
    import math

    t_c = t_kelvin - 273.15
    # Saturation vapor pressure (hPa) via Tetens
    es = 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))
    # Mixing ratio from specific humidity
    w = q / (1 - q) if q < 1 else q
    # Saturation mixing ratio
    ws = 0.622 * es / (p_hpa - es) if p_hpa > es else 1.0
    # Relative humidity
    rh = (w / ws) * 100 if ws > 0 else 0
    return max(0, min(100, rh))


def estimate_cloud_cover(rh_850, rh_700, rh_500, tcwv):
    """Estimate cloud fraction (0-100) from multi-level relative humidity + tcwv.

    Based on Sundqvist (1989) cloud parameterization used in NWP models:
    cloud_fraction = 1 - sqrt((1 - RH) / (1 - RH_crit))
    where RH_crit varies by level (~0.7 for low, ~0.6 for mid, ~0.5 for high).
    """
    import math

    def sundqvist_cf(rh_pct, rh_crit):
        rh = rh_pct / 100
        if rh <= rh_crit:
            return 0.0
        if rh >= 1.0:
            return 1.0
        return 1.0 - math.sqrt(max(0, (1 - rh) / (1 - rh_crit)))

    # Cloud fraction at each level
    cf_low = sundqvist_cf(rh_850, 0.70) if rh_850 is not None else 0
    cf_mid = sundqvist_cf(rh_700, 0.60) if rh_700 is not None else 0
    cf_high = sundqvist_cf(rh_500, 0.50) if rh_500 is not None else 0

    # Total cloud cover: maximum-random overlap
    # Simplified: use max overlap (conservative estimate)
    total_cf = 1 - (1 - cf_low) * (1 - cf_mid) * (1 - cf_high)

    # Adjust with tcwv as sanity check
    # Very low tcwv (<8 kg/m2) → cap cloud cover
    if tcwv is not None and tcwv < 8:
        total_cf = min(total_cf, 0.2)

    return round(total_cf * 100, 1)


def cloud_cover_to_weather_code(cloud_pct, tp=None):
    """Convert cloud cover % + precipitation to WMO weather code."""
    # Check precipitation first (tp in kg/m2 per 6h step)
    if tp is not None and tp > 1.0:
        if tp > 10:
            return 65  # heavy rain
        if tp > 3:
            return 63  # moderate rain
        return 61      # slight rain

    if cloud_pct < 10:
        return 0   # clear
    if cloud_pct < 30:
        return 1   # mainly clear
    if cloud_pct < 60:
        return 2   # partly cloudy
    if cloud_pct < 85:
        return 3   # overcast
    return 3       # overcast


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

    # Get number of time steps from any variable
    all_vars = EXTRACT_VARS + CLOUD_VARS
    nsteps = None
    for var in all_vars:
        if var in io_backend:
            nsteps = io_backend[var].shape[1]
            break
    if nsteps is None:
        return [], 0, 0

    for step in range(nsteps):
        lead_hours = step * 6
        entry = {"lead_hours": lead_hours}

        for var in EXTRACT_VARS:
            if var in io_backend:
                val = float(io_backend[var][0, step, lat_idx, lon_idx])
                entry[var] = val

        # Extract cloud variables
        cloud_data = {}
        for var in CLOUD_VARS:
            if var in io_backend:
                cloud_data[var] = float(io_backend[var][0, step, lat_idx, lon_idx])

        # Compute relative humidity at each pressure level
        rh_850, rh_700, rh_500 = None, None, None
        if "q850" in cloud_data and "t850" in cloud_data:
            rh_850 = specific_to_relative_humidity(cloud_data["q850"], cloud_data["t850"], 850)
        if "q700" in cloud_data and "t700" in cloud_data:
            rh_700 = specific_to_relative_humidity(cloud_data["q700"], cloud_data["t700"], 700)
        if "q500" in cloud_data and "t500" in cloud_data:
            rh_500 = specific_to_relative_humidity(cloud_data["q500"], cloud_data["t500"], 500)

        # Estimate cloud cover
        tcwv = entry.get("tcwv")
        cloud_pct = estimate_cloud_cover(rh_850, rh_700, rh_500, tcwv)
        tp = entry.get("tp")
        weather_code = cloud_cover_to_weather_code(cloud_pct, tp)

        entry["rh_850"] = round(rh_850, 1) if rh_850 is not None else None
        entry["rh_700"] = round(rh_700, 1) if rh_700 is not None else None
        entry["rh_500"] = round(rh_500, 1) if rh_500 is not None else None
        entry["cloud_pct"] = cloud_pct
        entry["weather_code"] = weather_code

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
                "cloud_pcts": [],
                "weather_codes": [],
            }

        if "temp_f" in entry:
            daily[day_key]["temps_f"].append(entry["temp_f"])
        if "wind_mph" in entry:
            daily[day_key]["winds_mph"].append(entry["wind_mph"])
        if "pressure_inhg" in entry:
            daily[day_key]["pressures"].append(entry["pressure_inhg"])
        if "cloud_pct" in entry:
            daily[day_key]["cloud_pcts"].append(entry["cloud_pct"])
        if "weather_code" in entry:
            daily[day_key]["weather_codes"].append(entry["weather_code"])

    result = []
    for day_key in sorted(daily.keys()):
        d = daily[day_key]
        temps = d["temps_f"]
        winds = d["winds_mph"]
        pressures = d["pressures"]
        clouds = d["cloud_pcts"]
        codes = d["weather_codes"]
        avg_cloud = round(sum(clouds) / len(clouds), 1) if clouds else None
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
                "cloud_avg_pct": avg_cloud,
                "weather_code": cloud_cover_to_weather_code(avg_cloud) if avg_cloud is not None else 2,
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
