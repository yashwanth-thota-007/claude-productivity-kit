#!/usr/bin/env python3
"""
On-demand weekly rollup — called by /weekly command.

Reads all session replays from the past 7 days, uses Haiku to synthesise
a personal weekly retro: what shipped, patterns, wins, and what to focus on next week.
"""
import json, os, sys, boto3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID   = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
)

MAX_REPLAY_CHARS = 1500   # per replay — keeps total prompt manageable
MAX_REPLAYS      = 20     # cap to avoid token overflow

PROMPT = """\
You are writing a personal weekly engineering retro from session replay notes.

WEEK: {week}
SESSIONS ({count} total):

{replays}

Write a tight weekly retro with exactly these sections:

## What Shipped This Week
Bullet list of concrete deliverables: features built, bugs fixed, PRs merged, tools created. Group by project/theme if there are clear clusters. Be specific.

## Patterns & Observations
2-3 bullets: recurring themes, what you gravitated toward, how you worked (e.g. lots of refactoring, heavy on tooling, deep focus sessions vs scattered).

## Wins
2-3 bullets: things that went particularly well — a tricky problem solved cleanly, a tool that paid off, a good decision.

## Carried Over / Next Week
Bullet list of things explicitly marked pending across sessions, plus any natural continuations you can infer.

## One Thing to Do Differently
Single sentence — a concrete process or habit tweak based on this week's patterns.

Be specific and honest. No filler. Use backticks for file/function names."""


def load_replays(days: int) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=days)
    replays = []
    if not REPLAYS_DIR.exists():
        return replays
    for f in sorted(REPLAYS_DIR.glob("*.md"), reverse=True):
        try:
            # filename: 2026-06-27_15-01_d666bbb7.md
            date_str = f.stem[:16]
            file_dt  = datetime.strptime(date_str, "%Y-%m-%d_%H-%M")
            if file_dt < cutoff:
                continue
            text = f.read_text()
            replays.append({"file": f.name, "date": file_dt, "text": text})
        except Exception:
            continue
    return replays[:MAX_REPLAYS]


def format_replays(replays: list[dict]) -> str:
    parts = []
    for r in replays:
        header = f"### {r['date'].strftime('%a %b %d %H:%M')} — {r['file']}"
        body   = r["text"][:MAX_REPLAY_CHARS]
        if len(r["text"]) > MAX_REPLAY_CHARS:
            body += "\n...(truncated)"
        parts.append(f"{header}\n{body}")
    return "\n\n---\n\n".join(parts)


def generate_weekly(replays: list[dict]) -> str:
    week_start = (datetime.now() - timedelta(days=7)).strftime("%b %d")
    week_end   = datetime.now().strftime("%b %d, %Y")

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": PROMPT.format(
            week=f"{week_start} – {week_end}",
            count=len(replays),
            replays=format_replays(replays),
        )}],
    }
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["content"][0]["text"].strip()


def main():
    days = 7
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            pass

    replays = load_replays(days)
    if not replays:
        print(f"No session replays found in the past {days} days.")
        print(f"Replays are saved to: {REPLAYS_DIR}")
        sys.exit(0)

    print(f"_Analysing {len(replays)} sessions from the past {days} days…_\n")

    try:
        summary = generate_weekly(replays)
    except Exception as e:
        print(f"Error generating weekly: {e}", file=sys.stderr)
        sys.exit(1)

    # Save to replays dir
    ts    = datetime.now().strftime("%Y-%m-%d")
    fname = REPLAYS_DIR / f"{ts}_weekly.md"
    fname.write_text(f"# Weekly Retro — {ts}\n\n{summary}\n")

    print(summary)
    print(f"\n_Saved to `{fname.name}`_")


if __name__ == "__main__":
    main()
