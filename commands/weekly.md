# Weekly

Generate a personal weekly engineering retro from the last 7 days of session replays.

## Instructions

1. Run the weekly rollup:
```bash
python3 ~/.claude/scripts/weekly.py
```

2. Display the output as-is — it's formatted markdown.

3. Ask: "Want me to post this to Slack?" and if yes run:
```bash
python3 ~/.claude/scripts/weekly.py --post
```

## Options

- Last 7 days (default): `python3 ~/.claude/scripts/weekly.py`
- Custom lookback: `python3 ~/.claude/scripts/weekly.py 14` (14 days)

## Notes

- Reads from `~/.claude/session-replays/` — populated automatically at end of every session
- Also saved to `~/.claude/session-replays/YYYY-MM-DD_weekly.md`
- Powered by Haiku — runs in ~5 seconds
