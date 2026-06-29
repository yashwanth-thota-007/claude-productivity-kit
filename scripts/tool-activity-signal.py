#!/usr/bin/env python3
import json, sys, pathlib, time

try:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input", {})
    preview = (
        tool_input.get("command") or
        tool_input.get("file_path") or
        tool_input.get("prompt") or
        ""
    )[:80]
    sig = {
        "session_id": data.get("session_id", ""),
        "tool": data.get("tool_name", ""),
        "preview": preview,
        "ts": time.time(),
    }
    (pathlib.Path.home() / ".claude" / "tool-running.json").write_text(json.dumps(sig))
except Exception:
    pass
