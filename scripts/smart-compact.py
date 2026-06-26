#!/usr/bin/env python3
"""
PreCompact hook — fires just before Claude Code auto-compacts the context.
Reads the transcript, extracts a structured summary of in-progress work,
and injects it as a systemMessage so the compacted context preserves it.

Config: ~/.claude/smart-compact.config.json
  trigger_threshold_percent  - only run if context usage >= this (default 80)
  max_files                  - max changed files to list (default 20)
  max_commands               - max bash commands to list (default 5)
  max_user_messages          - max user messages to include (default 3)
  context_window_tokens      - used to calculate % from token counts (default 200000)
"""
import json, sys, os, re
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude" / "smart-compact.config.json"

DEFAULTS = {
    "trigger_threshold_percent": 80,
    "max_files": 20,
    "max_commands": 5,
    "max_user_messages": 3,
    "context_window_tokens": 200000,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return {**DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return DEFAULTS.copy()


def estimate_context_percent(entries: list[dict], context_window: int):
    """Return % used from the most recent assistant usage block, or None if unavailable."""
    for e in reversed(entries):
        if e.get("type") == "assistant":
            usage = e.get("message", {}).get("usage", {})
            if usage:
                total = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
                if total > 0:
                    return min(100.0, (total / context_window) * 100)
    return None


def parse_transcript(path: str) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def extract_user_messages(entries: list[dict]) -> list[str]:
    msgs = []
    for e in entries:
        if e.get("type") == "user":
            msg = e.get("message", {})
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        msgs.append(block["text"].strip())
            elif isinstance(msg, str):
                msgs.append(msg.strip())
    return msgs


def extract_tool_calls(entries: list[dict]) -> list[dict]:
    """Return last N tool calls with name + key input fields."""
    calls = []
    for e in entries:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })
    return calls[-20:]  # last 20 tool calls only


def extract_file_changes(tool_calls: list[dict], max_files: int) -> list[str]:
    files = []
    for c in tool_calls:
        if c["name"] in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            path = c["input"].get("file_path") or c["input"].get("path", "")
            if path and path not in files:
                files.append(path)
    return files[:max_files]


def extract_bash_commands(tool_calls: list[dict], max_commands: int) -> list[str]:
    cmds = []
    for c in tool_calls:
        if c["name"] == "Bash":
            cmd = c["input"].get("command", "")
            # Trim rtk wrapper if present
            cmd = re.sub(r"^rtk bash -c\s+'?", "", cmd).rstrip("'")
            if cmd and len(cmd) < 200:
                cmds.append(cmd)
    return cmds[-max_commands:]


def extract_current_task(user_msgs: list[str]) -> str:
    """Best guess at the current task from recent user messages."""
    # Walk backwards, skip short confirmations
    for msg in reversed(user_msgs):
        if len(msg) > 20 and not re.match(r"^(yes|no|ok|sure|lgtm|great|thanks|looks good)$", msg.lower().strip()):
            # Truncate long ones
            return msg[:300] + ("..." if len(msg) > 300 else "")
    return user_msgs[-1][:300] if user_msgs else "unknown"


def extract_todos(entries: list[dict]) -> list[str]:
    """Pull any TodoWrite items that are still in_progress or pending."""
    todos = []
    for e in entries:
        if e.get("type") == "tool_result":
            for block in e.get("content", []):
                if isinstance(block, dict) and "todos" in str(block):
                    try:
                        data = json.loads(block.get("content", "[]"))
                        for t in data:
                            if t.get("status") in ("in_progress", "pending"):
                                todos.append(f"[{t['status']}] {t['content']}")
                    except Exception:
                        pass
    return todos[-10:]


def build_summary(transcript_path: str, cfg: dict) -> str:
    entries = parse_transcript(transcript_path)
    if not entries:
        return ""

    # Threshold check — skip if context isn't high enough
    threshold = cfg["trigger_threshold_percent"]
    pct = estimate_context_percent(entries, cfg["context_window_tokens"])
    if pct is not None and pct < threshold:
        return ""

    user_msgs = extract_user_messages(entries)
    tool_calls = extract_tool_calls(entries)
    changed_files = extract_file_changes(tool_calls, cfg["max_files"])
    recent_commands = extract_bash_commands(tool_calls, cfg["max_commands"])
    todos = extract_todos(entries)
    current_task = extract_current_task(user_msgs) if user_msgs else ""
    pct_str = f"{pct:.0f}%" if pct is not None else "unknown"

    lines = [f"=== SMART COMPACT SUMMARY (context at ~{pct_str}, threshold {threshold}%) ===", ""]

    if current_task:
        lines += ["## Current task", current_task, ""]

    if todos:
        lines += ["## Open todos"]
        lines += todos
        lines += [""]

    if changed_files:
        lines += ["## Files modified this session"]
        lines += [f"  - {f}" for f in changed_files]
        lines += [""]

    if recent_commands:
        lines += [f"## Recent shell commands (last {cfg['max_commands']})"]
        lines += [f"  $ {c}" for c in recent_commands]
        lines += [""]

    if user_msgs:
        n = cfg["max_user_messages"]
        lines += [f"## Last {n} user messages"]
        for m in user_msgs[-n:]:
            lines += [f"  > {m[:200]}"]
        lines += [""]

    lines += ["=== END SUMMARY — resume from here after compaction ==="]
    return "\n".join(lines)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cfg = load_config()
    transcript_path = hook_input.get("transcript_path", "")
    summary = build_summary(transcript_path, cfg)

    if summary:
        print(json.dumps({"systemMessage": summary}))


if __name__ == "__main__":
    main()
