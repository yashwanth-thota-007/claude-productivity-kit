#!/usr/bin/env python3
"""
On-demand session summarizer — called by /summarize command.

Reads the current live session transcript, generates a structured summary
using Haiku, and prints it as markdown for Claude to display inline.

Usage: python3 ~/.claude/scripts/summarize.py [session_id]
  session_id defaults to ~/.claude/active-session-id
"""
import json, os, sys, boto3
from pathlib import Path
from typing import Optional
from datetime import datetime

TRANSCRIPTS_DIR = Path.home() / ".claude" / "projects"
CONTRACTS_DIR   = Path.home() / ".claude" / "session-contracts"
REPLAYS_DIR     = Path.home() / ".claude" / "session-replays"

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID   = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
)

MAX_CHARS = 20000  # larger than session-replay.py since this is on-demand

PROMPT = """\
You are summarising an in-progress Claude Code session for the developer.

SESSION CONTRACT (goal set at start):
{contract}

TRANSCRIPT (most recent messages first, up to {chars} chars):
{transcript}

Write a tight markdown summary with exactly these sections:

## What's Happened So Far
Bullet list of concrete things done: files touched, features built, bugs fixed, decisions made. Be specific — file names, function names, commands run. Max 8 bullets.

## Key Decisions
2-3 bullets: non-obvious choices and the reasoning behind them.

## Current State
1-2 sentences: where things stand right now, what is working, what is in-progress.

## Remaining / Next Steps
Bullet list of open items or natural next actions. If the session goal is fully done, say so.

Be factual, terse, and specific. No filler. Use backticks for file paths and code."""


def find_transcript(session_id: str) -> Optional[Path]:
    for project_dir in TRANSCRIPTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        t = project_dir / f"{session_id}.jsonl"
        if t.exists():
            return t
    return None


def extract_text(transcript: Path, max_chars: int) -> str:
    lines = transcript.read_text().strip().splitlines()
    parts = []
    total = 0
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            role = entry.get("type", "")
            if role == "user":
                for block in entry.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = f"USER: {block['text'][:600]}"
                        parts.append(text)
                        total += len(text)
            elif role == "assistant":
                for block in entry.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = f"ASSISTANT: {block['text'][:1000]}"
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
        return "No formal contract — general session."
    try:
        c = json.loads(path.read_text())
        if c.get("_skipped"):
            return "General conversation — no formal goal set."
        return (
            f"Title: {c.get('session_title', 'untitled')}\n"
            f"Product goal: {c.get('product', '?')}\n"
            f"Process goal: {c.get('process', '?')}\n"
            f"Performance goal: {c.get('performance', '?')}"
        )
    except Exception:
        return "Could not parse contract."


def summarize(session_id: str) -> str:
    transcript_path = find_transcript(session_id)
    if not transcript_path:
        return f"No transcript found for session `{session_id[:8]}`."

    transcript = extract_text(transcript_path, MAX_CHARS)
    if not transcript:
        return "Transcript is empty — nothing to summarize yet."

    contract = load_contract(session_id)

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": PROMPT.format(
            contract=contract,
            chars=len(transcript),
            transcript=transcript,
        )}],
    }
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    summary = json.loads(resp["body"].read())["content"][0]["text"].strip()

    # Also save to replays dir so it's browsable later
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    ts    = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fname = REPLAYS_DIR / f"{ts}_{session_id[:8]}_ondemand.md"
    title = "Session"
    contract_path = CONTRACTS_DIR / f"{session_id}.json"
    try:
        title = json.loads(contract_path.read_text()).get("session_title", "Session")
    except Exception:
        pass
    fname.write_text(f"# {title}\n\n**Session:** `{session_id[:8]}`  \n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')} _(on-demand)_\n\n{summary}\n")

    return summary


def main():
    # Accept session_id as arg or read from active-session-id file
    if len(sys.argv) > 1:
        session_id = sys.argv[1]
    else:
        sid_file = Path.home() / ".claude" / "active-session-id"
        if not sid_file.exists():
            print("No active session found. Pass session_id as argument.")
            sys.exit(1)
        session_id = sid_file.read_text().strip()

    if not session_id:
        print("No active session ID.")
        sys.exit(1)

    try:
        print(summarize(session_id))
    except Exception as e:
        print(f"Error generating summary: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
