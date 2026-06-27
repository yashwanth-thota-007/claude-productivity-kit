#!/usr/bin/env python3
"""
standup.py — summarise yesterday's session replays into a Slack standup.

Usage:
  python3 ~/.claude/scripts/standup.py           # post to Slack
  python3 ~/.claude/scripts/standup.py --dry-run # print only, no post

Reads SLACK_STANDUP_WEBHOOK from environment (set in settings.json env block).
"""
import json, os, sys, boto3, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timedelta

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID   = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)

PROMPT = """\
You are writing a brief async standup message for a developer's Slack channel.

SESSION REPLAYS FROM THE LAST 24 HOURS:
{replays}

TODAY'S DATE: {today}

Write a standup in this exact format (plain text, no markdown headers):

*Yesterday* _(or recent sessions)_
• <what was done — one bullet per major thing, max 5>

*Today*
• <what's next based on Pending/Next Steps in the replays — max 3>

*Blockers*
None. _(or list if any blockers were mentioned)_

Rules:
- Be specific: mention feature names, file names, decisions made
- Keep each bullet under 15 words
- Don't say "I worked on" — just state what was done/planned
- Output the standup text only, no preamble"""



def recent_replays(hours: int = 24) -> list[str]:
    if not REPLAYS_DIR.exists():
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    files = sorted(REPLAYS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            break
        result.append(f.read_text())
    return result


def generate_standup(replays: list[str]) -> str:
    combined = "\n\n---\n\n".join(replays)[:8000]
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    prompt = PROMPT.format(
        replays=combined,
        today=datetime.now().strftime("%A, %B %d %Y"),
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["content"][0]["text"].strip()


def post_to_slack(webhook_url: str, text: str) -> bool:
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.URLError as e:
        print(f"Slack post failed: {e}", file=sys.stderr)
        return False


def main():
    dry_run = "--dry-run" in sys.argv

    replays = recent_replays(hours=24)
    if not replays:
        # fall back to last 72h if nothing in the last 24h (weekends, etc.)
        replays = recent_replays(hours=72)

    if not replays:
        print("No session replays found in the last 72 hours. Nothing to post.")
        sys.exit(0)

    standup = generate_standup(replays)

    print(standup)
    print()

    if dry_run:
        print("(dry-run — not posting to Slack)")
        sys.exit(0)

    webhook = os.environ.get("SLACK_STANDUP_WEBHOOK", "")
    if not webhook:
        print("No SLACK_STANDUP_WEBHOOK in environment — set it in settings.json env block.", file=sys.stderr)
        sys.exit(1)

    ok = post_to_slack(webhook, standup)
    if ok:
        print("Posted to Slack.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
