# Health

Check all kit dependencies and configuration are working correctly.

## Instructions

```bash
python3 ~/.claude/scripts/health_check.py
```

Display the output as-is. If any checks fail, help the user fix them based on the error notes.

## What It Checks

- `claude` CLI present and version
- `jq`, `node/npx`, `gh` CLI
- All Python packages for voice menubar (whisper, rumps, sounddevice, webrtcvad, etc.)
- AWS credentials reachable with configured profile
- `settings.json` exists and has required keys
- `.env` file present (for Slack webhook)
- `mcp.json` present
- LaunchAgents loaded (voice-menubar, standup)
- Session replays directory and count
- All scripts present
