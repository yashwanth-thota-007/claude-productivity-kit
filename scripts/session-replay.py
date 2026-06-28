#!/usr/bin/env python3
"""
Stop hook — generates a session replay/handoff doc.

Reads the session transcript + contract, uses Haiku to produce a structured
markdown summary, writes it to ~/.claude/session-replays/<session_id>.md.
"""
import json, os, sys, time, subprocess, boto3
from pathlib import Path
from datetime import datetime

SCRIPTS_DIR = Path(__file__).parent

CONTRACTS_DIR  = Path.home() / ".claude" / "session-contracts"
REPLAYS_DIR    = Path.home() / ".claude" / "session-replays"
TRANSCRIPTS_DIR = Path.home() / ".claude" / "projects"

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID   = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)

MAX_TRANSCRIPT_CHARS = 12000  # keep cost low — enough for a solid summary

SUMMARY_PROMPT = """\
You are summarising a Claude Code session for a developer handoff doc.

SESSION CONTRACT:
{contract}

TRANSCRIPT EXCERPT (last ~{chars} chars of the session):
{transcript}

Write a concise markdown handoff doc with exactly these sections:

## Goal
One sentence — what the session set out to accomplish.

## What Was Done
Bullet list of concrete actions: files created/modified, features built, bugs fixed, decisions made. Be specific (file names, function names, commands). Max 10 bullets.

## Key Decisions
2-4 bullets covering non-obvious choices made and why (tradeoffs, rejected alternatives).

## Pending / Next Steps
Bullet list of open items, TODOs, or natural next actions. If nothing is pending, write "None — session goal fully achieved."

## Resume Context
2-3 sentences a future session needs to pick up immediately: what state the code is in, what to do first, any gotchas.

Be factual and terse. No fluff. Use backticks for file paths, function names, commands."""


DISCERNMENT_LOG = Path.home() / ".claude" / "discernment-log.jsonl"


def parse_entries(transcript_path: str) -> list:
    """Return all parsed JSONL entries from the transcript file."""
    if not transcript_path or not Path(transcript_path).exists():
        return []
    entries = []
    for line in Path(transcript_path).read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def compute_metrics(entries: list, session_id: str) -> str:
    """Compute session metrics from transcript entries and discernment log."""
    # Duration — timestamps may be ISO strings or unix floats
    duration = "unknown"
    raw_ts = [e["timestamp"] for e in entries if "timestamp" in e]
    if len(raw_ts) >= 2:
        try:
            from datetime import datetime as _dt
            def _to_float(ts):
                if isinstance(ts, (int, float)):
                    return float(ts)
                # ISO-8601 e.g. "2026-06-29T00:03:12.123Z"
                ts = ts.rstrip("Z").replace("T", " ")
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return _dt.strptime(ts, fmt).timestamp()
                    except ValueError:
                        continue
                return None
            t0 = _to_float(raw_ts[0])
            t1 = _to_float(raw_ts[-1])
            if t0 is not None and t1 is not None:
                delta_sec = t1 - t0
                duration = f"{int(delta_sec // 60)} min"
        except Exception:
            pass

    # Message counts
    user_count = sum(1 for e in entries if e.get("type") == "user")
    asst_count = sum(1 for e in entries if e.get("type") == "assistant")

    # Tool calls
    tool_counts: dict = {}
    for e in entries:
        if e.get("type") != "assistant":
            continue
        for block in e.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "unknown")
                tool_counts[name] = tool_counts.get(name, 0) + 1
    total_tools = sum(tool_counts.values())
    top3 = sorted(tool_counts.items(), key=lambda x: -x[1])[:3]
    top3_str = ", ".join(f"{n}x{c}" for n, c in top3) if top3 else "none"

    # Tokens from last assistant entry's usage block
    input_tokens = output_tokens = "unknown"
    for e in reversed(entries):
        if e.get("type") == "assistant":
            usage = e.get("message", {}).get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", "unknown")
                output_tokens = usage.get("output_tokens", "unknown")
            break

    # Discernment average for this session
    disc_avg = "n/a"
    if DISCERNMENT_LOG.exists():
        scores = []
        for line in DISCERNMENT_LOG.read_text().strip().splitlines():
            try:
                rec = json.loads(line)
                if rec.get("session_id") == session_id:
                    scores.append(float(rec["composite"]))
            except Exception:
                continue
        if scores:
            disc_avg = f"{sum(scores) / len(scores):.1f}/10"

    return (
        "## Metrics\n"
        f"- Duration: {duration} (first → last message timestamp delta)\n"
        f"- Messages: {user_count} user, {asst_count} assistant\n"
        f"- Tool calls: {total_tools} total (top 3 tools: {top3_str})\n"
        f"- Input tokens: {input_tokens} (from last assistant usage block)\n"
        f"- Output tokens: {output_tokens} (from last assistant usage block)\n"
        f"- Discernment avg: {disc_avg} (from discernment-log.jsonl)\n"
    )


def find_transcript(session_id: str) -> str:
    """Find the transcript file for this session across all project dirs."""
    for project_dir in TRANSCRIPTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        transcript = project_dir / f"{session_id}.jsonl"
        if transcript.exists():
            return str(transcript)
    return ""


def extract_transcript_text(transcript_path: str, max_chars: int) -> str:
    """Extract assistant + user messages from transcript, newest-first up to max_chars."""
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    lines = Path(transcript_path).read_text().strip().splitlines()
    parts = []
    total = 0
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            role = entry.get("type", "")
            if role == "user":
                content = entry.get("message", {})
                if isinstance(content, dict):
                    for block in content.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = f"USER: {block['text'][:500]}"
                            parts.append(text)
                            total += len(text)
            elif role == "assistant":
                message = entry.get("message", {})
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = f"ASSISTANT: {block['text'][:800]}"
                        parts.append(text)
                        total += len(text)
            if total >= max_chars:
                break
        except Exception:
            continue
    parts.reverse()
    return "\n\n".join(parts)[-max_chars:]


def load_contract(session_id: str) -> str:
    path = CONTRACTS_DIR / f"{session_id}.json"
    if not path.exists():
        return "No contract found."
    try:
        c = json.loads(path.read_text())
        if c.get("_skipped"):
            return "General conversation — no formal contract."
        return (
            f"Title: {c.get('session_title', 'untitled')}\n"
            f"Product: {c.get('product', '?')}\n"
            f"Process: {c.get('process', '?')}\n"
            f"Performance: {c.get('performance', '?')}\n"
            f"Effort: {c.get('effort', 'normal')}"
        )
    except Exception:
        return "Could not parse contract."


def generate_summary(contract: str, transcript: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    prompt = SUMMARY_PROMPT.format(
        contract=contract,
        chars=len(transcript),
        transcript=transcript,
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["content"][0]["text"].strip()


def _run_bg(cmd: list):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    if not session_id:
        sys.exit(0)

    # Skip if no contract (session never got going)
    contract_path = CONTRACTS_DIR / f"{session_id}.json"
    if not contract_path.exists():
        sys.exit(0)

    contract   = load_contract(session_id)
    transcript_path = find_transcript(session_id)
    entries    = parse_entries(transcript_path)
    transcript = extract_transcript_text(transcript_path, MAX_TRANSCRIPT_CHARS)

    if not transcript:
        sys.exit(0)

    try:
        summary = generate_summary(contract, transcript)
    except Exception as e:
        sys.exit(0)

    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    ts    = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fname = REPLAYS_DIR / f"{ts}_{session_id[:8]}.md"

    # Parse title from contract for the header
    title = "Session"
    try:
        c = json.loads(contract_path.read_text())
        title = c.get("session_title", "Session")
    except Exception:
        pass

    metrics = compute_metrics(entries, session_id)
    doc = f"# {title}\n\n**Session:** `{session_id[:8]}`  \n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{summary}\n\n{metrics}"
    fname.write_text(doc)

    # Index into personal sessions.db + inject Obsidian wikilinks
    cwd = hook_input.get("cwd", str(Path.home()))
    _run_bg(["python3", str(SCRIPTS_DIR / "index_session.py"), str(fname)])
    _run_bg(["python3", str(SCRIPTS_DIR / "project_mental_model.py"), "--update", str(fname), cwd])

    # Write a signal file so the voice-menubar overlay shows a session summary
    import re
    goal_match = re.search(r"## Goal\n(.+?)(?:\n\n|\n##)", doc, re.DOTALL)
    goal = goal_match.group(1).strip()[:120] if goal_match else title
    pending_match = re.search(r"## Pending.*?\n(.+?)(?:\n##|\Z)", doc, re.DOTALL)
    pending_lines = pending_match.group(1).strip().splitlines() if pending_match else []
    # Pull discernment avg from metrics block
    disc_match = re.search(r"Discernment avg: (.+?)(?:\n|$)", doc)
    disc = disc_match.group(1).strip() if disc_match else ""
    summary_lines = [f"✅ {goal}"]
    if disc:
        summary_lines.append(f"Quality: {disc}")
    if pending_lines:
        summary_lines.append("Next:")
        for l in pending_lines[:3]:
            clean = l.lstrip("- •").strip()
            if clean and clean.lower() not in ("none", "none — session goal fully achieved."):
                summary_lines.append(f"  • {clean[:80]}")
    signal = {
        "content": "\n".join(summary_lines),
        "session_id": session_id,
        "ts": time.time(),
        "type": "session_end",
    }
    signal_path = Path.home() / ".claude" / "session-end-signal.json"
    signal_path.write_text(json.dumps(signal))

    # Surface the file path to the user via systemMessage
    print(json.dumps({"systemMessage": f"📝 Session replay saved: {fname.name}"}))


if __name__ == "__main__":
    main()
