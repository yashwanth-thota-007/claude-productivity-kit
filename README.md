# claude-productivity-kit

A macOS menu bar app + Claude Code hooks that turn Claude CLI into a fully-featured developer productivity layer.

## Features

### Voice Menubar (`scripts/voice-menubar.py`)
- **Double-tap Ctrl** — record voice, transcribe via Whisper, paste into active window
- **Double Ctrl+V** — save clipboard image to session folder, paste `@path` into active window
- **WebRTC VAD** — auto-stops recording 2s after last detected speech
- **Pomodoro** — auto-starts from session effort level (quick→25m, normal→50m, deep→90m), manual presets, countdown in menu bar icon + Claude status line, 5-min warning + expiry notification
- **Model switcher** — switch Whisper model (tiny/base/small/medium/large) from menu
- **Transcript history** — last 5 transcripts in menu, click to copy, rolling 100-entry JSONL log

### Claude Code Hooks
- **Session contract** (`scripts/session-contract.py`) — extracts Product/Process/Performance goals + effort level from first message via Haiku, re-injects as system context each turn, detects topic drift
- **Discernment scorer** (`scripts/discernment-scorer.py`) — scores every response 1-10 across Product/Process/Performance using Haiku + session contract, blocks with retry nudge if below threshold, session-level miscalibration offset after 3 low scores
- **Work advisor** (`scripts/start-work-advisor.py`) — suggests git worktree isolation on task-intent prompts
- **Smart compact** (`scripts/smart-compact.py`) — PreCompact hook
- **History cleanup** (`scripts/cleanup_history.py`) — SessionStart hook, prunes transcripts older than 30 days
- **Session image cleanup** — Stop hook deletes session-scoped paste-images folder on exit
- **Session replay** (`scripts/session-replay.py`) — Stop hook generates structured markdown handoff doc at session end via Haiku, writes to `~/.claude/session-replays/`

### Slash Commands
- `/refine` — improve a rough prompt using 6 prompting techniques
- `/discernment-stats` — show scoring trends across sessions
- `/auto-pr` — draft PR title + body from latest session replay + git diff, then create via `gh pr create`
- `/standup` — generate daily standup from recent session replays, optionally post to Slack

## Requirements

- macOS (Apple Silicon tested)
- Python 3.13 via Homebrew: `/opt/homebrew/bin/python3.13`
- AWS credentials with Bedrock access (eu-central-1) for Haiku scoring

## Install

```bash
# Python deps
/opt/homebrew/bin/pip3.13 install \
  openai-whisper sounddevice numpy pyperclip rumps pynput \
  pyobjc-framework-Cocoa pyobjc-framework-Quartz \
  webrtcvad boto3 --break-system-packages

# LaunchAgent (auto-start on login)
cp com.claude.voice-menubar.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.claude.voice-menubar.plist

# Standup cron (9am Mon-Fri → Slack)
echo "SLACK_STANDUP_WEBHOOK=https://hooks.slack.com/your-webhook-url" >> ~/.claude/.env
cp com.claude.standup.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.claude.standup.plist
```

Grant **Accessibility** permission to `/opt/homebrew/bin/python3.13` in  
System Settings → Privacy & Security → Accessibility.

Grant **Screen Recording** permission to `/opt/homebrew/bin/python3.13` in  
System Settings → Privacy & Security → Screen Recording.  
(Required for the Option+Ctrl screenshot feature to capture window contents — without it screencapture returns only desktop wallpaper.)

## Shell aliases (`~/.zshrc`)

```zsh
alias c='claude'
alias cvm='/opt/homebrew/bin/python3.13 ~/.claude/scripts/voice-menubar.py'
alias cvimg='/opt/homebrew/bin/python3.13 ~/.claude/scripts/paste-image.py'
```

## Roadmap

- [ ] Voice-to-Claude (hands-free prompting)
- [ ] Focus guard (2-hour session interrupt)
- [x] Session replay / handoff doc
- [x] Auto PR description
- [ ] Smart screenshot (region capture → auto-inject)
- [x] Ambient standup (cron → Slack)
- [ ] Team contract dashboard
