# claude-productivity-kit

Personal AI infrastructure built on top of Claude Code CLI — voice control, session intelligence, computer use, and a portable setup you can take to any org.

> Built in 1 day. Costs ~$0.10–0.50/day in Haiku background calls.

---

## What's Inside

### 1. Voice Menubar (`scripts/voice-menubar.py`)
A macOS menu bar app that gives Claude a physical presence on your machine.

| Hotkey | Action |
|--------|--------|
| Double-tap **Ctrl** | Record voice → Whisper transcription → paste into active window |
| Double-tap **Cmd** | Record voice → send directly to Claude, stream response in overlay |
| **Option+Ctrl** | Region screenshot → save to session folder → paste `@path` |
| Double **Ctrl+V** | Save clipboard image → paste `@path` into active window |
| Say **"Hey Claude"** | Hands-free recording trigger (wake word, toggleable) |

**Features:**
- Live transcription overlay (WKWebView, renders markdown/tables/images)
- Computer use agent mode — speak a goal, Claude controls your screen
  - Browser tasks → Playwright MCP (no coordinate calibration)
  - Native UI tasks → cursor calibration loop (move → screenshot → verify → click)
- Pomodoro timer — auto-starts from session effort level, countdown in menu bar
- Voice session continuity via `--resume` across turns
- Whisper model switcher (tiny → large) from menu
- Silence threshold, overlay position, Pomodoro presets — all configurable

### 2. Session Intelligence Pipeline

Every Claude Code session runs through this pipeline automatically:

```
Session start
    └── session-contract.py    extract Product/Process/Performance goals via Haiku
                               re-inject as system context each turn, detect drift

Each response
    └── discernment-scorer.py  score 1–10 across P/P/P using session contract
                               block + retry nudge if below threshold (default 6.5)

Session end
    ├── session-replay.py      structured handoff doc → ~/.claude/session-replays/
    └── cleanup hooks          delete paste-images, clear active-session-id
```

**On-demand commands:**
- `/summarize` — inline mid-session summary (What's Done / Key Decisions / Current State / Next Steps)
- `/weekly` — roll up last 7 days of replays into a personal retro
- `/search-sessions <query>` — search replays by keyword, date, or natural language
- `/standup` — generate daily standup from replays, optionally post to Slack

### 3. Slash Commands & Agents
- **23 slash commands** in `commands/` — `/prime`, `/code-review`, `/pr-review`, `/architecture-review`, `/ultra-think`, `/auto-pr`, `/create-jira-task`, `/sprint-planning`, and more
- **13 sub-agents** in `agents/` — frontend-developer, backend-architect, debugger, code-reviewer, documentation-expert, and more
- **9 skill packs** in `skills/` — canvas-design, algorithmic-art, slack-gif-creator, pdf-processing-pro, webapp-testing, and more

### 4. MCP Servers (`mcp.json`)
- `memory`, `fetch`, two Playwright server variants
- Plugins: Playwright, Atlassian, Datadog, Figma, Superpowers, dx

---

## Install

### 1. Clone & configure
```bash
git clone https://github.com/yashwanth-thota-007/claude-productivity-kit.git ~/.claude
cd ~/.claude
cp settings.example.json settings.json
# Edit settings.json — fill in AWS_PROFILE, AWS_REGION, model IDs
bash setup.sh
```

### 2. Python dependencies
```bash
/opt/homebrew/bin/pip3.13 install \
  openai-whisper sounddevice numpy pyperclip rumps pynput mistune \
  pyobjc-framework-Cocoa pyobjc-framework-Quartz \
  webrtcvad boto3 --break-system-packages
```

### 3. LaunchAgents
```bash
cp com.claude.voice-menubar.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.claude.voice-menubar.plist

# Optional: daily standup to Slack
echo "SLACK_STANDUP_WEBHOOK=https://hooks.slack.com/your-webhook-url" >> ~/.claude/.env
cp com.claude.standup.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.claude.standup.plist
```

### 4. macOS permissions
System Settings → Privacy & Security:
- **Accessibility** → grant `/opt/homebrew/bin/python3.13`
- **Screen Recording** → grant `/opt/homebrew/bin/python3.13`
- **Microphone** → grant on first use

### 5. Verify
```bash
python3 ~/.claude/scripts/health_check.py
```

---

## Environment Variables

Set in `settings.json` under `"env"`:

| Variable | Purpose |
|----------|---------|
| `AWS_PROFILE` | AWS profile with Bedrock access |
| `AWS_REGION` | AWS region (e.g. `us-east-1`) |
| `CLAUDE_CODE_USE_BEDROCK` | Set to `"1"` to route via Bedrock |
| `ANTHROPIC_MODEL` | Main model ID (Sonnet/Opus) |
| `ANTHROPIC_SMALL_FAST_MODEL` | Fast model ID (Haiku) for background scripts |
| `ENABLE_PROMPT_CACHING_1H_BEDROCK` | Enable 1h prompt cache on Bedrock |

---

## File Structure

```
~/.claude/
├── scripts/            Core automation scripts
│   ├── voice-menubar.py          Menu bar app + computer use agent
│   ├── session-contract.py       Session goal extraction (UserPromptSubmit hook)
│   ├── discernment-scorer.py     Response quality scoring (Stop hook)
│   ├── session-replay.py         End-of-session handoff doc (Stop hook)
│   ├── summarize.py              On-demand mid-session summary
│   ├── weekly.py                 Weekly retro from session replays
│   ├── search_sessions.py        Search session replays
│   ├── standup.py                Daily standup generator
│   ├── auto-pr.py                PR description from replay + diff
│   ├── context-monitor.py        Status line (context % + Pomodoro)
│   └── smart-compact.py          PreCompact hook
├── commands/           Slash commands
├── agents/             Sub-agent definitions
├── skills/             Skill packs
├── session-replays/    Auto-generated session summaries (gitignored)
├── settings.example.json
├── mcp.json
├── setup.sh
├── com.claude.voice-menubar.plist
└── com.claude.standup.plist
```

---

## Portability

No org-specific values in this repo. LaunchAgent plists use `CLAUDE_HOME` placeholders replaced by `setup.sh`. Live config (`settings.json`, `.env`) is gitignored.

To onboard at a new org: clone → copy `settings.example.json` → fill in values → `bash setup.sh`.
