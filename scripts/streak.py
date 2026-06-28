#!/usr/bin/env python3
"""Count consecutive daily session streaks from session-replay files."""

import re
from datetime import date, timedelta
from pathlib import Path

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}")
SKIP = ("_weekly", "_ondemand")


def iter_replay_files():
    if not REPLAYS_DIR.exists():
        return
    for f in REPLAYS_DIR.iterdir():
        if f.suffix == ".md" and not any(kw in f.name for kw in SKIP):
            yield f


def collect_dates():
    dates = set()
    for f in iter_replay_files():
        m = FILENAME_RE.match(f.name)
        if m:
            try:
                dates.add(date.fromisoformat(m.group(1)))
            except ValueError:
                pass
    return dates


def current_streak(dates, today):
    streak, d = 0, today
    while d in dates:
        streak += 1
        d -= timedelta(days=1)
    return streak


def longest_streak(dates):
    if not dates:
        return 0
    best = run = 1
    for a, b in zip(sorted(dates), sorted(dates)[1:]):
        run = run + 1 if b - a == timedelta(days=1) else 1
        best = max(best, run)
    return best


def main():
    dates = collect_dates()
    total = sum(1 for _ in iter_replay_files())

    if not dates:
        print("No sessions yet. Start one to begin your streak!")
        return

    today = date.today()
    cur = current_streak(dates, today)
    best = longest_streak(dates)
    days = len(dates)

    print(f"🔥 Streak: {cur} day{'s' if cur != 1 else ''}  (longest: {best})")
    print(f"📅 Sessions: {total} total across {days} day{'s' if days != 1 else ''}")


if __name__ == "__main__":
    main()
