---
allowed-tools: Bash
description: Live kit status — active session, streak, Pomodoro, context, focus lock
model: haiku
---

# /status — Kit Status

Show a live snapshot of the productivity kit's current state.

## Instructions

Run all checks and display a clean status panel:

```bash
python3 -c "
import json, time
from pathlib import Path
from datetime import datetime

home = Path.home() / '.claude'
lines = ['## Kit Status — ' + datetime.now().strftime('%H:%M')]

# Active session
vs = home / 'voice-session-id'
if vs.exists():
    sid = vs.read_text().strip()
    contract_path = home / 'session-contracts' / f'{sid}.json'
    if contract_path.exists():
        try:
            c = json.loads(contract_path.read_text())
            title = c.get('session_title', sid[:8])
            effort = c.get('effort', 'normal')
            lines.append(f'Session  : {title} [{effort}]')
        except Exception:
            lines.append(f'Session  : {sid[:8]}...')
    else:
        lines.append(f'Session  : {sid[:8]}...')
else:
    lines.append('Session  : none')

# Focus lock
lock_path = home / 'focus-lock.json'
if lock_path.exists():
    try:
        lock = json.loads(lock_path.read_text())
        if lock.get('active'):
            goal = lock.get('goal', '')[:60]
            blocked = lock.get('blocked_topics', [])
            lines.append(f'Focus    : {goal}')
            if blocked:
                lines.append(f'  Blocked: {chr(44).join(blocked)}')
        else:
            lines.append('Focus    : none')
    except Exception:
        lines.append('Focus    : none')
else:
    lines.append('Focus    : none')

# Pomodoro
pomo = home / 'pomodoro-state.json'
if pomo.exists():
    try:
        p = json.loads(pomo.read_text())
        if p.get('active'):
            started = p.get('started_at', 0)
            minutes = p.get('minutes', 25)
            elapsed = int((time.time() - started) / 60)
            remaining = minutes - elapsed
            if remaining > 0:
                lines.append(f'Pomodoro : {remaining}m remaining ({minutes}m block)')
            else:
                lines.append(f'Pomodoro : done (overran {-remaining}m)')
        else:
            lines.append('Pomodoro : idle')
    except Exception:
        lines.append('Pomodoro : idle')
else:
    lines.append('Pomodoro : idle')

# Streak
replays_dir = home / 'session-replays'
if replays_dir.exists():
    from datetime import timedelta
    dates = set()
    for f in replays_dir.glob('*.md'):
        if '_weekly' in f.name or '_ondemand' in f.name:
            continue
        try:
            dates.add(datetime.strptime(f.stem[:10], '%Y-%m-%d').date())
        except Exception:
            pass
    streak = 0
    d = datetime.now().date()
    while d in dates:
        streak += 1
        d -= timedelta(days=1)
    lines.append(f'Streak   : {streak} day{\"s\" if streak != 1 else \"\"}')
else:
    lines.append('Streak   : 0 days')

# Today sessions
today_str = datetime.now().strftime('%Y-%m-%d')
today_count = sum(1 for f in (replays_dir.glob('*.md') if replays_dir.exists() else [])
                  if f.name.startswith(today_str))
lines.append(f'Today    : {today_count} session{\"s\" if today_count != 1 else \"\"}')

# Recent discernment avg (last 10 scores)
log = home / 'discernment-log.jsonl'
if log.exists():
    try:
        recent = []
        for line in log.read_text().splitlines()[-10:]:
            try:
                recent.append(float(json.loads(line)['composite']))
            except Exception:
                pass
        if recent:
            avg = sum(recent) / len(recent)
            lines.append(f'Quality  : {avg:.1f}/10 (last {len(recent)} responses)')
    except Exception:
        pass

print(chr(10).join(lines))
"
```
