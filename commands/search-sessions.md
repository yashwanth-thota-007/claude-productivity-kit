# Search Sessions

Search past session replays by keyword, date, or natural language.

## Instructions

Run the search and display results:

```bash
python3 ~/.claude/scripts/search_sessions.py "$QUERY"
```

## Examples

```bash
# Keyword search
python3 ~/.claude/scripts/search_sessions.py "voice menubar"

# Natural language date
python3 ~/.claude/scripts/search_sessions.py "last tuesday"
python3 ~/.claude/scripts/search_sessions.py "yesterday"

# Today's sessions
python3 ~/.claude/scripts/search_sessions.py --today

# Yesterday's sessions
python3 ~/.claude/scripts/search_sessions.py --yesterday

# Exact date
python3 ~/.claude/scripts/search_sessions.py --date 2026-06-27

# Last N sessions
python3 ~/.claude/scripts/search_sessions.py --last 5

# Semantic (no keyword match → asks Haiku)
python3 ~/.claude/scripts/search_sessions.py "auth work"
```

## Notes

- Keyword search is instant (no API cost)
- Semantic fallback uses Haiku when no keyword match found
- All replays live in `~/.claude/session-replays/`
