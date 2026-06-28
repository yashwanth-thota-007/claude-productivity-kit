---
description: Morning startup ritual — PRs, yesterday, streak, what's next.
allowed-tools: Bash
---

Good morning. Running your morning brief now.

## 1. PRs & Yesterday's Context

```bash
python3 ~/.claude/scripts/daily_brief.py --dry-run
```

## 2. Today's Sessions

```bash
python3 ~/.claude/scripts/search_sessions.py --today
```

## 3. Yesterday's Sessions

```bash
python3 ~/.claude/scripts/search_sessions.py --yesterday
```

## 4. Streak

```bash
python3 ~/.claude/scripts/streak.py
```

---

Run `/standup` to post to Slack, `/dashboard` to open stats, `/focus <goal>` to lock in.
