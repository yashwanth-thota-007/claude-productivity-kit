---
allowed-tools: Read, Write, Bash
argument-hint: <focus goal> [--block <topic1,topic2>]
description: Lock the session onto a single goal, blocking scope creep and off-topic detours
model: haiku
---

# /focus — Session Focus Lock

**Arguments:** $ARGUMENTS

Parse the arguments:
- Everything before `--block` is the **focus goal**
- Everything after `--block` is a comma-separated list of topics to actively block

If no arguments given, show the current focus lock (if any) for this session.

## Instructions

### If setting a focus goal:

1. Read the active session ID:
```bash
cat ~/.claude/active-session-id 2>/dev/null || echo ""
```

2. Write a focus-lock file:
```bash
python3 -c "
import json, sys, time
from pathlib import Path

session_id = open(Path.home() / '.claude' / 'active-session-id').read().strip()
args = '$ARGUMENTS'

# Parse goal and blocked topics
if '--block' in args:
    parts = args.split('--block', 1)
    goal = parts[0].strip()
    blocked = [t.strip() for t in parts[1].split(',') if t.strip()]
else:
    goal = args.strip()
    blocked = []

lock = {
    'session_id': session_id,
    'goal': goal,
    'blocked_topics': blocked,
    'ts': time.time(),
    'active': True,
}
path = Path.home() / '.claude' / 'focus-lock.json'
path.write_text(json.dumps(lock, indent=2))
print(f'Focus locked: {goal}')
if blocked:
    print(f'Blocking: {', '.join(blocked)}')
"
```

3. Inject a hard focus constraint into the system prompt by printing:

```
Focus lock active for this session:

**Goal:** <the focus goal>
**Blocked topics:** <list, or "none">

CONSTRAINTS (enforce strictly):
- Every response must advance the stated goal above
- If asked about a blocked topic, acknowledge it briefly and redirect back to the goal
- If a request is clearly off-topic (not related to the goal), flag it: "⚠️ Focus lock: this looks off-topic. Shall I address it anyway, or stay focused on [goal]?"
- Do not silently drift — if you notice the conversation moving away from the goal, say so

This lock was set by the user with /focus and should be respected for the remainder of the session.
```

### If no arguments (show current lock):

```bash
python3 -c "
import json
from pathlib import Path
p = Path.home() / '.claude' / 'focus-lock.json'
if not p.exists():
    print('No focus lock active.')
else:
    lock = json.loads(p.read_text())
    print(f'Goal: {lock[\"goal\"]}')
    print(f'Blocked: {lock.get(\"blocked_topics\") or \"none\"}')
    print(f'Active: {lock.get(\"active\", False)}')
"
```

### To clear a focus lock, the user can run `/focus clear`:

If $ARGUMENTS == "clear":
```bash
python3 -c "
from pathlib import Path
p = Path.home() / '.claude' / 'focus-lock.json'
if p.exists():
    import json
    lock = json.loads(p.read_text())
    lock['active'] = False
    p.write_text(json.dumps(lock, indent=2))
    print('Focus lock cleared.')
else:
    print('No focus lock to clear.')
"
```
