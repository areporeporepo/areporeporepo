#!/usr/bin/env python3
"""WiGLE WiFi collector — runs daily via GitHub Actions.

Collects 1 location per run, round-robins between locations.
Persists all data in a secret GitHub Gist (JSON).
Respects WiGLE rate limits: 1 API call per run, 1 run per day.

Env vars (from repo secrets):
  WIGLE_API_NAME, WIGLE_API_TOKEN — WiGLE API credentials
  WIGLE_DATA_GIST_ID — secret gist for data persistence
  GH_TOKEN — GitHub token for gist read/write
"""

import json, os, subprocess, sys, base64, urllib.request
from datetime import datetime, timezone

# --- Config ---
RESULTS_PER_PAGE = 100

LOCATIONS = {
    "nvidia_hq": {
        "label": "NVIDIA HQ — Voyager",
        "lat1": 37.3680, "lat2": 37.3740,
        "lng1": -121.9670, "lng2": -121.9600,
    },
    "home_paloalto": {
        "label": "Home — Palo Alto",
        "lat1": 37.4450, "lat2": 37.4510,
        "lng1": -122.1400, "lng2": -122.1320,
    },
}


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def gist_read(gist_id, filename="wigle_data.json"):
    """Read JSON data from a GitHub Gist."""
    result = subprocess.run(
        ["gh", "gist", "view", gist_id, "-f", filename],
        capture_output=True, text=True,
        env={**os.environ, "GH_TOKEN": os.environ["GH_TOKEN"]},
    )
    if result.returncode != 0:
        log(f"Gist read failed: {result.stderr.strip()}")
        return None
    return json.loads(result.stdout)


def gist_write(gist_id, data, filename="wigle_data.json"):
    """Write JSON data to a GitHub Gist. Retries on HTTP 500."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp_path = f.name

    for attempt in range(3):
        result = subprocess.run(
            ["gh", "gist", "edit", gist_id, "-f", f"{filename}:{tmp_path}"],
            capture_output=True, text=True,
            env={**os.environ, "GH_TOKEN": os.environ["GH_TOKEN"]},
        )
        if result.returncode == 0:
            os.unlink(tmp_path)
            return True
        log(f"  Gist write attempt {attempt+1}/3 failed: {result.stderr.strip()}")
        if attempt < 2:
            import time; time.sleep(5)

    os.unlink(tmp_path)
    return False


def wigle_search(lat1, lat2, lng1, lng2, first=0):
    """Query WiGLE search API. Returns (results_list, ok)."""
    api_name = os.environ["WIGLE_API_NAME"]
    api_token = os.environ["WIGLE_API_TOKEN"]
    creds = base64.b64encode(f"{api_name}:{api_token}".encode()).decode()

    url = (
        f"https://api.wigle.net/api/v2/network/search"
        f"?latrange1={lat1}&latrange2={lat2}"
        f"&longrange1={lng1}&longrange2={lng2}"
        f"&resultsPerPage={RESULTS_PER_PAGE}&first={first}"
    )
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Basic {creds}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("success"):
                return data, True
            log(f"  API error: {data.get('message', 'unknown')}")
            return data, False
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        log(f"  HTTP {e.code}: {body[:200]}")
        return {}, False
    except Exception as e:
        log(f"  Request failed: {e}")
        return {}, False


def main():
    gist_id = os.environ.get("WIGLE_DATA_GIST_ID")
    if not gist_id:
        log("ERROR: WIGLE_DATA_GIST_ID not set")
        sys.exit(1)

    # Load persisted state from gist
    log("Reading data gist...")
    db = gist_read(gist_id)
    if db is None:
        db = {}

    state = db.pop("state", {"last_location_idx": -1})

    # Pick next location (round-robin)
    loc_keys = list(LOCATIONS.keys())
    idx = (state["last_location_idx"] + 1) % len(loc_keys)
    loc_key = loc_keys[idx]
    loc_cfg = LOCATIONS[loc_key]

    # Get existing cache for this location
    existing = {}
    for net in db.get(loc_key, []):
        existing[net["netid"]] = net

    log(f"Collecting: {loc_cfg['label']} — cache has {len(existing)} networks")

    # Query next page
    offset = len(existing)
    data, ok = wigle_search(
        loc_cfg["lat1"], loc_cfg["lat2"],
        loc_cfg["lng1"], loc_cfg["lng2"],
        first=offset,
    )

    if not ok:
        log("Query failed — will retry tomorrow")
        sys.exit(0)  # exit clean so Actions doesn't alert

    total = data.get("totalResults", 0)
    results = data.get("results", [])
    log(f"  Got {len(results)} results (offset {offset}, total {total})")

    # Merge
    for r in results:
        existing[r["netid"]] = r

    # Rebuild db
    db[loc_key] = list(existing.values())
    # Preserve other locations
    for k in loc_keys:
        if k not in db:
            db[k] = []

    state["last_location_idx"] = idx
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_location"] = loc_key
    state["last_result_count"] = len(results)
    db["state"] = state

    # Summary
    for k in loc_keys:
        log(f"  {LOCATIONS[k]['label']}: {len(db.get(k, []))} cached")

    # Write back to gist
    log("Writing data gist...")
    if gist_write(gist_id, db):
        log("Done — gist updated.")
    else:
        log("ERROR: Failed to write gist after retries")
        sys.exit(1)


if __name__ == "__main__":
    main()
