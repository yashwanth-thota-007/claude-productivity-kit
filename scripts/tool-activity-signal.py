#!/usr/bin/env python3
import json, os, sys, pathlib, subprocess, time

try:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "")

    # Full command/path — no truncation; overlay will wrap it
    preview = (
        tool_input.get("command") or
        tool_input.get("file_path") or
        tool_input.get("prompt") or
        ""
    )

    # Resolve human-readable session title from contract file
    session_title = ""
    if session_id:
        contract = pathlib.Path.home() / ".claude" / "session-contracts" / f"{session_id}.json"
        if contract.exists():
            try:
                c = json.loads(contract.read_text())
                session_title = c.get("session_title", "")
            except Exception:
                pass
    if not session_title:
        session_title = session_id[:8] + "…" if session_id else "unknown session"

    # Capture the controlling terminal of this hook process so the overlay
    # can route Allow/Deny keystrokes to the exact iTerm2 tab
    tty = ""
    try:
        raw = subprocess.check_output(
            ["ps", "-o", "tty=", "-p", str(os.getpid())],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if raw and raw != "??":
            tty = f"/dev/{raw}" if not raw.startswith("/") else raw
    except Exception:
        pass

    sig = {
        "session_id": session_id,
        "session_title": session_title,
        "tool": data.get("tool_name", ""),
        "preview": preview,
        "tty": tty,
        "ts": time.time(),
    }
    (pathlib.Path.home() / ".claude" / "tool-running.json").write_text(json.dumps(sig))
except Exception:
    pass
