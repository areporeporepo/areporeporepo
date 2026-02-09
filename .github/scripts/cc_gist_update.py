#!/usr/bin/env python3
"""Update Claude Code usage gist. Runs in GitHub Actions.

State stored in a separate hidden gist (data). The visible pinned
gist only has the bar + grid. Auto-resets bar after 5h.
"""
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone

DATA_ROWS = 4
WEEKS_PER_ROW = 5
BAR_WIDTH = 20
STALE_HOURS = 5
LEVELS = {0: "·", 1: "░", 2: "█"}
CONTENT_FILENAME = "\u2800"
PT = timezone(timedelta(hours=-8))

CONTENT_GIST_ID = os.environ.get("CC_GIST_ID", "")
DATA_GIST_ID = os.environ.get("CC_DATA_GIST_ID", "")


def gh_api(method, path, **fields):
    cmd = ["gh", "api", "--method", method, path]
    for k, v in fields.items():
        cmd += ["-f", f"{k}={v}"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return r.stdout


def read_data():
    try:
        raw = gh_api("GET", f"/gists/{DATA_GIST_ID}")
        gist = json.loads(raw)
        f = gist.get("files", {}).get("cc_data.json")
        if f and f.get("content"):
            return json.loads(f["content"])
    except Exception:
        pass
    return {"pct": 0, "ts": None, "dates": []}


def write_data(data):
    gh_api("PATCH", f"/gists/{DATA_GIST_ID}",
           **{f"files[cc_data.json][content]": json.dumps(data)})


def write_content(content):
    gh_api("PATCH", f"/gists/{CONTENT_GIST_ID}",
           **{f"files[{CONTENT_FILENAME}][content]": content,
              "description": " "})


def usage_bar(pct):
    pct = max(0, min(100, pct))
    filled = round(pct / 100 * BAR_WIDTH)
    empty = BAR_WIDTH - filled
    return f"{'🔵' * filled}{'⚪' * empty}"


def generate_grid(dates):
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
    data = read_data()

    pct = data.get("pct", 0)
    ts_str = data.get("ts")
    if ts_str:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=PT)
        if (datetime.now(PT) - ts).total_seconds() > STALE_HOURS * 3600:
            pct = 0
            data["pct"] = 0
    else:
        pct = 0

    bar = usage_bar(pct)
    grid = generate_grid(data.get("dates", []))
    content = f"{bar}\n{grid}"

    write_data(data)
    write_content(content)
    print(content)
    print("\nupdated gist")


if __name__ == "__main__":
    main()
