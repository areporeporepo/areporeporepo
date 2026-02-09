#!/usr/bin/env python3
"""Update Claude Code usage gist. Runs locally or in GitHub Actions.

State is stored in the gist itself (data.json) so both local /maxed
and the hourly GitHub Action can read/write it.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path

# Config
DATA_ROWS = 4
WEEKS_PER_ROW = 5
BAR_WIDTH = 20
STALE_HOURS = 5
LEVELS = {0: "·", 1: "░", 2: "█"}
CONTENT_FILENAME = "\u2800"  # braille blank - invisible title
DATA_FILENAME = "data.json"

# Resolve gist ID from env or local file
GIST_ID = os.environ.get("CC_GIST_ID") or os.environ.get("GIST_ID", "")
if not GIST_ID:
    gist_file = Path.home() / ".claude" / "claudemaxxing_gist_id"
    if gist_file.exists():
        GIST_ID = gist_file.read_text().strip()

PT = timezone(timedelta(hours=-8))  # Pacific Time (PST)


def gh_api(method, path, **fields):
    cmd = ["gh", "api", "--method", method, path]
    for k, v in fields.items():
        cmd += ["-f", f"{k}={v}"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return r.stdout


def read_gist_data():
    """Read data.json from the gist."""
    try:
        raw = gh_api("GET", f"/gists/{GIST_ID}")
        gist = json.loads(raw)
        data_file = gist.get("files", {}).get(DATA_FILENAME)
        if data_file and data_file.get("content"):
            return json.loads(data_file["content"])
    except Exception:
        pass
    return {"pct": 0, "ts": None, "dates": []}


def write_gist(content, data):
    """Write both the visible content and data.json to the gist."""
    data_json = json.dumps(data)
    gh_api("PATCH", f"/gists/{GIST_ID}",
           **{f"files[{CONTENT_FILENAME}][content]": content,
              f"files[{DATA_FILENAME}][content]": data_json,
              "description": " "})


def usage_bar(pct):
    pct = max(0, min(100, pct))
    filled = round(pct / 100 * BAR_WIDTH)
    empty = BAR_WIDTH - filled
    return f"{'🔵' * filled}{'⚪' * empty}"


def generate_grid(dates):
    from collections import Counter
    counts = dict(Counter(dates))
    today = datetime.now(PT).date()
    current_monday = today - timedelta(days=today.weekday())
    total_weeks = DATA_ROWS * WEEKS_PER_ROW
    start_monday = current_monday - timedelta(weeks=total_weeks - 1)

    lines = []
    for row_start in range(0, total_weeks, WEEKS_PER_ROW):
        row = ""
        for w in range(row_start, row_start + WEEKS_PER_ROW):
            if w > row_start:
                row += " "
            week_monday = start_monday + timedelta(weeks=w)
            for day in range(7):
                d = week_monday + timedelta(days=day)
                if d > today:
                    row += "·"
                else:
                    n = counts.get(d.strftime("%Y-%m-%d"), 0)
                    row += LEVELS[min(n, 2)]
        lines.append(row)
    lines.reverse()
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--usage", type=int, help="Set usage percentage (0-100)")
    parser.add_argument("--ci", action="store_true", help="Running in CI")
    args = parser.parse_args()

    data = read_gist_data()

    # Update usage if provided
    if args.usage is not None:
        data["pct"] = args.usage
        data["ts"] = datetime.now(PT).isoformat()
        # Log today
        today = datetime.now(PT).strftime("%Y-%m-%d")
        if "dates" not in data:
            data["dates"] = []
        data["dates"].append(today)

    # Check staleness - reset bar if usage is old
    pct = data.get("pct", 0)
    ts_str = data.get("ts")
    if ts_str:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=PT)
        age_hours = (datetime.now(PT) - ts).total_seconds() / 3600
        if age_hours > STALE_HOURS:
            pct = 0
            data["pct"] = 0
    else:
        pct = 0

    bar = usage_bar(pct)
    grid = generate_grid(data.get("dates", []))
    content = f"{bar}\n{grid}"

    write_gist(content, data)
    print(content)
    print("\nupdated gist")


if __name__ == "__main__":
    main()
