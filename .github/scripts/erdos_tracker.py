#!/usr/bin/env python3
"""Erdos Problems Tracker — pinned gist box.

Fetches problem data from teorth/erdosproblems, adds compact forum
activity signals, and updates a GitHub pinned gist.
"""

import csv
import html
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import yaml

DATA_URL = "https://raw.githubusercontent.com/teorth/erdosproblems/main/data/problems.yaml"
FORUM_URL = "https://www.erdosproblems.com/forum/"
GIST_FILE = Path.home() / ".claude" / "erdos_gist_id"
HISTORY_FILE = Path.home() / ".claude" / "erdos_history.csv"
GIST_FILENAME = "erdos-problems.txt"
DEFAULT_GIST_ID = "ff84b5c87973d3c31df45b142fe1cb6b"

CI_MODE = "--ci" in sys.argv
PREVIEW_MODE = "--preview" in sys.argv

# Status groupings
PROVED_STATES = {"proved", "proved (lean)", "proven"}
DISPROVED_STATES = {"disproved", "disproved (lean)"}
SOLVED_STATES = {"solved", "solved (lean)"}
LEAN_STATES = {"proved (lean)", "disproved (lean)", "solved (lean)"}

# Kept for historical CSV continuity.
AI_PRIMARY_TOTAL = 80

THREAD_LINK_RE = re.compile(
    r"""<a[^>]+href=["'][^"']*/forum/(?:thread|discuss)/\d+[^"']*["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
PROBLEM_NUM_RE = re.compile(r"\bproblem\s*#?\s*(\d{1,4})\b", re.IGNORECASE)
POSTS_RE = re.compile(r"(\d+)\s+posts?\b", re.IGNORECASE)
COMPACT_AGE_RE = re.compile(r"\b(\d+)\s*(mo|m|h|d|w|y)\s*ago\b", re.IGNORECASE)
VERBOSE_AGE_RE = re.compile(
    r"\b(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago\b",
    re.IGNORECASE,
)

AGE_UNIT_TO_MIN = {
    "m": 1,
    "minute": 1,
    "minutes": 1,
    "h": 60,
    "hour": 60,
    "hours": 60,
    "d": 60 * 24,
    "day": 60 * 24,
    "days": 60 * 24,
    "w": 60 * 24 * 7,
    "week": 60 * 24 * 7,
    "weeks": 60 * 24 * 7,
    "mo": 60 * 24 * 30,
    "month": 60 * 24 * 30,
    "months": 60 * 24 * 30,
    "y": 60 * 24 * 365,
    "year": 60 * 24 * 365,
    "years": 60 * 24 * 365,
}

LOCAL_DATA_FALLBACKS = [
    Path.home() / "erdosproblems" / "data" / "problems.yaml",
]


def fetch_problems():
    """Fetch and parse problems.yaml from GitHub."""
    try:
        with urlopen(DATA_URL, timeout=30) as resp:
            return yaml.safe_load(resp.read().decode("utf-8"))
    except Exception as exc:
        for path in LOCAL_DATA_FALLBACKS:
            if path.exists():
                print(f"Remote data fetch failed ({exc}); using local data: {path}")
                return yaml.safe_load(path.read_text(encoding="utf-8"))
        raise


def fetch_forum_page():
    """Fetch forum HTML text."""
    with urlopen(FORUM_URL, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _parse_age(raw):
    compact = COMPACT_AGE_RE.search(raw)
    if compact:
        n = int(compact.group(1))
        unit = compact.group(2).lower()
        return f"{n}{unit}", n * AGE_UNIT_TO_MIN[unit]

    verbose = VERBOSE_AGE_RE.search(raw)
    if verbose:
        n = int(verbose.group(1))
        unit = verbose.group(2).lower()
        short = {
            "minute": "m",
            "minutes": "m",
            "hour": "h",
            "hours": "h",
            "day": "d",
            "days": "d",
            "week": "w",
            "weeks": "w",
            "month": "mo",
            "months": "mo",
            "year": "y",
            "years": "y",
        }[unit]
        return f"{n}{short}", n * AGE_UNIT_TO_MIN[unit]

    if "today" in raw.lower():
        return "0d", 0
    if "yesterday" in raw.lower():
        return "1d", 60 * 24
    return "?", 10**9


def _oeis_stage(problem):
    vals = [str(v).lower() for v in problem.get("oeis", [])]
    if "in progress" in vals:
        return "in progress"
    if "submitted" in vals:
        return "submitted"
    if "possible" in vals:
        return "possible"
    if any(re.match(r"^a\d+$", v) for v in vals):
        return "linked"
    if vals and all(v == "n/a" for v in vals):
        return "N/A"
    return "other"


def parse_forum_focus(forum_html, problems, limit=3):
    """Extract active problem threads from forum listing."""
    by_number = {str(p.get("number", "")): p for p in problems}
    focus = []
    seen = set()

    for match in THREAD_LINK_RE.finditer(forum_html):
        title = _strip_html(match.group(1))
        m_num = PROBLEM_NUM_RE.search(title)
        if not m_num:
            continue

        number = m_num.group(1)
        if number in seen or number not in by_number:
            continue

        end = match.end()
        context = _strip_html(forum_html[end:end + 600])
        p_match = POSTS_RE.search(context)
        posts = int(p_match.group(1)) if p_match else 0
        age_label, age_minutes = _parse_age(context)

        problem = by_number[number]
        state = str(problem.get("status", {}).get("state", "")).strip()
        item = {
            "number": number,
            "posts": posts,
            "age_label": age_label,
            "age_minutes": age_minutes,
            "state_tag": state or "unknown",
            "stage": _oeis_stage(problem),
        }
        focus.append(item)
        seen.add(number)

    focus.sort(key=lambda x: (x["age_minutes"], -x["posts"]))
    return focus[:limit]


def compute_stats(problems):
    """Compute counts from problem list."""
    proved = 0
    disproved = 0
    solved = 0
    formalized = 0
    lean_verified = 0
    oeis_in_progress = 0
    oeis_possible = 0
    oeis_linked = 0
    total = len(problems)

    for p in problems:
        state = p.get("status", {}).get("state", "").lower()
        if state in PROVED_STATES:
            proved += 1
        elif state in DISPROVED_STATES:
            disproved += 1
        elif state in SOLVED_STATES:
            solved += 1

        if state in LEAN_STATES:
            lean_verified += 1

        if p.get("formalized", {}).get("state", "").lower() == "yes":
            formalized += 1

        oeis_vals = [str(v).lower() for v in p.get("oeis", [])]
        if "in progress" in oeis_vals:
            oeis_in_progress += 1
        if "possible" in oeis_vals:
            oeis_possible += 1
        if any(re.match(r"^a\d+$", v) for v in oeis_vals):
            oeis_linked += 1

    resolved = proved + disproved + solved
    open_count = total - resolved

    return {
        "proved": proved + solved,  # combined "positive" resolutions
        "disproved": disproved,
        "open": open_count,
        "total": total,
        "resolved": resolved,
        "formalized": formalized,
        "lean_verified": lean_verified,
        "oeis_in_progress": oeis_in_progress,
        "oeis_possible": oeis_possible,
        "oeis_linked": oeis_linked,
    }


def make_progress_bar(resolved, total, width=38):
    """Generate a Unicode progress bar."""
    ratio = resolved / total if total else 0
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)


def generate_gist(stats, focus):
    """Generate the 5-line gist content."""
    pct = int(stats["resolved"] / stats["total"] * 100) if stats["total"] else 0
    bar = make_progress_bar(stats["resolved"], stats["total"])

    if focus:
        focus_line = " | ".join(
            f"#{x['number']} {x['state_tag']}/{x['stage']} {x['posts']}p·{x['age_label']}"
            for x in focus
        )
    else:
        focus_line = "forum unavailable"

    lines = [
        f"Erdős Problems  {stats['proved']}✓ {stats['disproved']}✗ {stats['open']}? / {stats['total']}",
        f"{bar} {pct}% resolved",
        focus_line,
        f"OEIS stage: in progress {stats['oeis_in_progress']} · possible {stats['oeis_possible']} · linked {stats['oeis_linked']}",
        f"status proved/disproved/solved (Lean): {stats['lean_verified']} · formalized yes: {stats['formalized']}",
    ]
    return "\n".join(lines)


def append_history(stats):
    """Append a row to the history CSV."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_exists = HISTORY_FILE.exists()

    with open(HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "proved", "disproved", "open", "formalized", "ai_primary"])
        writer.writerow([
            today,
            stats["proved"],
            stats["disproved"],
            stats["open"],
            stats["formalized"],
            AI_PRIMARY_TOTAL,
        ])


def create_gist(content):
    """Create a new gist and return the gist ID."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="erdos-") as f:
        f.write(content)
        tmp = f.name

    result = subprocess.run(
        ["gh", "gist", "create", tmp, "--filename", GIST_FILENAME, "--public", "--desc",
         "Erdős Problems Tracker — AI-era progress on 1000+ open problems"],
        capture_output=True, text=True, check=True,
    )
    Path(tmp).unlink()

    gist_url = result.stdout.strip()
    gist_id = gist_url.split("/")[-1]
    GIST_FILE.write_text(gist_id + "\n")
    print(f"Created gist: {gist_url}")
    return gist_id


def get_gist_id():
    """Get gist ID from env (CI) or file (local)."""
    if CI_MODE:
        gist_id = os.environ.get("ERDOS_GIST_ID", "").strip()
        return gist_id or DEFAULT_GIST_ID
    if GIST_FILE.exists():
        return GIST_FILE.read_text().strip()
    return ""


def update_gist(content):
    """Update an existing gist."""
    gist_id = get_gist_id()
    subprocess.run(
        ["gh", "api", "--method", "PATCH", f"/gists/{gist_id}",
         "-f", f"files[{GIST_FILENAME}][content]={content}"],
        check=True, capture_output=True,
    )
    print(f"Updated gist: {gist_id}")
    return gist_id


def main():
    print("Fetching problems.yaml...")
    problems = fetch_problems()

    print("Computing stats...")
    stats = compute_stats(problems)

    print("Fetching forum activity...")
    focus = []
    try:
        forum_html = fetch_forum_page()
        focus = parse_forum_focus(forum_html, problems)
        if focus:
            print(f"Forum focus threads: {', '.join('#' + x['number'] for x in focus)}")
        else:
            print("Forum parsed, no active problem threads found.")
    except Exception as exc:
        print(f"Forum fetch/parse failed: {exc}")

    content = generate_gist(stats, focus)
    print("\n" + content + "\n")

    if PREVIEW_MODE:
        print("Preview mode: skipping history write and gist update.")
        return

    if not CI_MODE:
        append_history(stats)

    gist_id = get_gist_id()
    if gist_id:
        update_gist(content)
    else:
        create_gist(content)

    print("Done.")


if __name__ == "__main__":
    main()
