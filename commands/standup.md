# Standup

Generate and optionally post a daily standup from recent session replays.

## Instructions

1. Run the standup script in dry-run mode first to preview:

```bash
python3 ~/.claude/scripts/standup.py --dry-run
```

2. Show the user the generated standup text.

3. Ask: "Want me to post this to Slack?"

4. If yes, run without `--dry-run`:

```bash
python3 ~/.claude/scripts/standup.py
```

5. Confirm whether it posted successfully.

## Notes

- Requires `SLACK_STANDUP_WEBHOOK=https://hooks.slack.com/...` in `~/.claude/.env`
- Looks back 24h for replays; falls back to 72h on weekends / after gaps
- Also runs automatically at 9am Mon–Fri via `com.claude.standup.plist` LaunchAgent
- To install the cron: `cp ~/.claude/com.claude.standup.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.claude.standup.plist`
- Logs: `/tmp/claude-standup.log`
