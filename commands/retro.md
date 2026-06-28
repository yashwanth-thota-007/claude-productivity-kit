---
allowed-tools: Read, Write, Bash
argument-hint: [--week | --days N]
description: Generate a weekly retrospective from session replays and discernment scores
model: sonnet
---

# /retro — Weekly Retrospective

Generate a retrospective from the last 7 days (or `--days N`) of session replays and quality scores.

## Arguments: $ARGUMENTS

Parse:
- `--week` or no args → last 7 days
- `--days N` → last N days

## Instructions

### Step 1: Gather data

```bash
python3 -c "
import json, re
from pathlib import Path
from datetime import datetime, timedelta

args = '$ARGUMENTS'
days = 7
if '--days' in args:
    try:
        days = int(args.split('--days')[1].strip().split()[0])
    except Exception:
        pass

cutoff = datetime.now() - timedelta(days=days)
replays_dir = Path.home() / '.claude' / 'session-replays'
log_path = Path.home() / '.claude' / 'discernment-log.jsonl'

# Load replays in window
replays = []
if replays_dir.exists():
    for f in sorted(replays_dir.glob('*.md'), reverse=True):
        try:
            date_str = f.stem[:16]
            date = datetime.strptime(date_str, '%Y-%m-%d_%H-%M')
            if date >= cutoff:
                text = f.read_text()
                goal_match = re.search(r'## Goal\n(.+?)(?:\n\n|\n##)', text, re.DOTALL)
                goal = goal_match.group(1).strip() if goal_match else f.stem
                pending_match = re.search(r'## Pending.*?\n(.+?)(?:\n##|\Z)', text, re.DOTALL)
                pending = pending_match.group(1).strip() if pending_match else ''
                metrics_match = re.search(r'## Metrics\n(.+?)(?:\n##|\Z)', text, re.DOTALL)
                metrics = metrics_match.group(1).strip() if metrics_match else ''
                replays.append({'date': date.strftime('%a %b %d %H:%M'), 'goal': goal[:120], 'pending': pending[:200], 'metrics': metrics[:300], 'file': str(f)})
        except Exception:
            pass

# Load discernment scores in window
scores = []
if log_path.exists():
    for line in log_path.read_text().splitlines():
        try:
            e = json.loads(line)
            scores.append(e['composite'])
        except Exception:
            pass
scores = scores[-50:]  # rough window

data = {
    'days': days,
    'session_count': len(replays),
    'replays': replays,
    'score_avg': round(sum(scores)/len(scores), 2) if scores else None,
    'score_min': min(scores) if scores else None,
    'score_max': max(scores) if scores else None,
    'score_count': len(scores),
}
print(json.dumps(data, indent=2))
"
```

### Step 2: Synthesize the retro

Using the data above, produce a structured retrospective in this format:

---

## 🔁 Retro — [date range]

### Sessions This Period
[N sessions completed — list each with date, goal, and whether it has pending items]

### Wins
[2-4 bullets: goals achieved, problems solved, things that worked well. Be specific.]

### Patterns
[2-3 bullets: recurring themes across sessions — what topics came up repeatedly, what tools were used most, any workflow patterns that emerged]

### Quality Trend
[Discernment avg over period: N.N/10 — one sentence interpreting what this means]

### Open Threads
[Consolidated list of all pending/next-steps items from session replays in this period]

### One Thing to Do Differently
[Single most impactful process improvement based on patterns above]

---

Keep it tight — a retro you'll actually read. No padding, no corporate speak. If there are fewer than 2 sessions, note that and keep it brief.

After generating the retro, ask: "Want me to save this to `~/.claude/session-replays/retro-[date].md`?"
