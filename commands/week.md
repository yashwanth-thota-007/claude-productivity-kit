---
allowed-tools: Bash
description: Current week's sessions at a glance — daily breakdown with titles and durations
model: haiku
---

Show this week's sessions as a daily breakdown (Mon–Sun).

```bash
python3 -c "
import re
from pathlib import Path
from datetime import datetime, timedelta

replays_dir = Path.home() / '.claude' / 'session-replays'
today = datetime.now().date()
monday = today - timedelta(days=today.weekday())
week_end = monday + timedelta(days=6)

header_start = monday.strftime('%b %-d')
header_end = week_end.strftime('%b %-d, %Y')
print(f'## Week of {header_start} – {header_end}')
print()

DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

total_sessions = 0
active_days = 0
streak = 0
checking_streak = True

day_session_counts = []

for i in range(7):
    day = monday + timedelta(days=i)
    prefix = day.strftime('%Y-%m-%d')
    files = sorted([f for f in replays_dir.glob(f'{prefix}_*.md')
                    if '_weekly' not in f.name and '_ondemand' not in f.name])

    by_hash = {}
    for f in files:
        parts = f.stem.split('_')
        h = parts[2] if len(parts) >= 3 else f.stem
        by_hash[h] = f
    sessions = list(by_hash.values())

    day_label = f'{DAY_NAMES[i]} {MONTH_ABBR[day.month-1]} {day.day}'
    is_today = day == today
    is_future = day > today
    n = len(sessions)
    total_sessions += n
    if n > 0:
        active_days += 1

    day_session_counts.append((day, n))

    if is_future:
        continue

    suffix = ' (today)' if is_today else ''
    if n == 0:
        print(f'{day_label}  0 sessions — no work')
    else:
        label = 'session' if n == 1 else 'sessions'
        print(f'{day_label}  {n} {label}{suffix}')
        for f in sessions:
            text = f.read_text()
            lines = text.splitlines()
            title = next((l[2:].strip() for l in lines if l.startswith('# ')), f.stem)
            m = re.search(r'Duration:\s*(\d+)\s*min', text)
            dur = f'{m.group(1)} min' if m else 'in progress' if is_today else '?'
            print(f'  • {title} [{dur}]')
    print()

# streak: count consecutive days with sessions going backward from today
for day, n in reversed(day_session_counts):
    if day > today:
        continue
    if n > 0:
        streak += 1
    else:
        break

print('─' * 35)
day_word = 'day' if active_days == 1 else 'days'
streak_word = 'day' if streak == 1 else 'days'
print(f'Total: {total_sessions} sessions across {active_days} {day_word} | Streak: {streak} {streak_word}')
"
```
