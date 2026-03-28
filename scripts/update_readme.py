#!/usr/bin/env python3
"""Reads workout data and updates README.md with health stats."""

import json
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKOUTS_FILE = REPO_ROOT / "data" / "workouts.json"
README_FILE = REPO_ROOT / "README.md"

START_MARKER = "<!-- WORKOUT-STATS:START -->"
END_MARKER = "<!-- WORKOUT-STATS:END -->"


def load_workouts():
    with open(WORKOUTS_FILE) as f:
        return json.load(f)


def compute_stats(workouts):
    if not workouts:
        return None

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def parse_date(w):
        date_str = w["date"].replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(date_str).replace(tzinfo=None)
        except ValueError:
            return datetime.fromisoformat(date_str.split("+")[0])

    total = len(workouts)
    total_minutes = sum(w["duration_minutes"] for w in workouts)
    total_calories = sum(w["calories_burned"] for w in workouts)

    weekly = [w for w in workouts if parse_date(w) >= week_ago]
    monthly = [w for w in workouts if parse_date(w) >= month_ago]

    type_counts = Counter(w["type"] for w in workouts)
    favorite = type_counts.most_common(1)[0][0] if type_counts else "N/A"

    latest = max(workouts, key=lambda w: w["date"])

    hrs = [w["heart_rate_avg"] for w in workouts if w.get("heart_rate_avg")]
    avg_hr = round(sum(hrs) / len(hrs)) if hrs else None

    distances = [w["distance_km"] for w in workouts if w.get("distance_km")]
    total_distance = round(sum(distances), 2)

    # Streak calculation
    dates = sorted(set(parse_date(w).date() for w in workouts), reverse=True)
    streak = 0
    check = now.date()
    for d in dates:
        if d == check:
            streak += 1
            check -= timedelta(days=1)
        elif d == check - timedelta(days=1):
            streak += 1
            check = d - timedelta(days=1)
        else:
            break

    return {
        "total": total,
        "total_minutes": total_minutes,
        "total_calories": total_calories,
        "total_distance_km": total_distance,
        "weekly_count": len(weekly),
        "weekly_calories": sum(w["calories_burned"] for w in weekly),
        "monthly_count": len(monthly),
        "monthly_calories": sum(w["calories_burned"] for w in monthly),
        "favorite_type": favorite,
        "avg_heart_rate": avg_hr,
        "streak": streak,
        "latest": latest,
    }


def build_stats_section(stats):
    if stats is None:
        return (
            f"{START_MARKER}\n"
            "### No workouts logged yet\n"
            "Waiting for the first Apple Watch workout...\n"
            f"{END_MARKER}"
        )

    latest = stats["latest"]
    hr_display = f"{stats['avg_heart_rate']} bpm" if stats["avg_heart_rate"] else "N/A"

    lines = [
        START_MARKER,
        "",
        "### Latest Workout",
        f"**{latest['type']}** — {latest['duration_minutes']} min, "
        f"{latest['calories_burned']} cal"
        + (f", {latest['distance_km']} km" if latest.get("distance_km") else "")
        + f" ({latest['date'][:10]})",
        "",
        "### This Week",
        f"| Workouts | Calories | Streak |",
        f"|----------|----------|--------|",
        f"| {stats['weekly_count']} | {stats['weekly_calories']} cal | {stats['streak']} day{'s' if stats['streak'] != 1 else ''} |",
        "",
        "### All Time",
        f"| Total Workouts | Total Time | Total Calories | Total Distance | Avg HR | Favorite |",
        f"|----------------|------------|----------------|----------------|--------|----------|",
        f"| {stats['total']} | {stats['total_minutes']} min | {stats['total_calories']} cal | {stats['total_distance_km']} km | {hr_display} | {stats['favorite_type']} |",
        "",
        END_MARKER,
    ]
    return "\n".join(lines)


def update_readme(stats_section):
    readme = README_FILE.read_text()

    if START_MARKER in readme and END_MARKER in readme:
        before = readme[: readme.index(START_MARKER)]
        after = readme[readme.index(END_MARKER) + len(END_MARKER) :]
        readme = before + stats_section + after
    else:
        readme = readme.rstrip() + "\n\n" + stats_section + "\n"

    README_FILE.write_text(readme)


def main():
    workouts = load_workouts()
    stats = compute_stats(workouts)
    section = build_stats_section(stats)
    update_readme(section)
    print(f"README updated — {len(workouts)} workouts tracked")


if __name__ == "__main__":
    main()
