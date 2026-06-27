# Summarize

Generate an on-demand summary of the current session — what's been done, key decisions, current state, and what's left.

## Instructions

1. Get the active session ID:
```bash
cat ~/.claude/active-session-id
```

2. Run the summarizer:
```bash
python3 ~/.claude/scripts/summarize.py
```

3. Display the output as-is — it's already formatted markdown.

## Notes

- Works mid-session, not just at the end
- Summary is also saved to `~/.claude/session-replays/<date>_<session>_ondemand.md`
- Uses the session contract (if one exists) as the goal context
- Powered by Haiku for speed — runs in ~3 seconds
