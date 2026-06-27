#!/usr/bin/env python3
"""
auto-pr.py — draft a PR title + body from the latest session replay + git diff.

Usage (called from /auto-pr slash command via Claude):
  python3 ~/.claude/scripts/auto-pr.py [/path/to/repo]

Prints a JSON object:
  { "title": "...", "body": "..." }
"""
import json, os, subprocess, sys, boto3
from pathlib import Path
from datetime import datetime

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"
AWS_REGION  = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID    = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)

MAX_DIFF_CHARS = 8000

PROMPT = """\
You are drafting a GitHub pull request description for a developer.

SESSION REPLAY (what was done this session):
{replay}

GIT DIFF SUMMARY (changed files and first {diff_chars} chars of diff):
{diff}

Write a pull request title and body. Rules:
- Title: conventional commit format, max 72 chars, no emoji. Example: "feat(voice-menubar): add session replay stop hook"
- Body: use exactly these sections (markdown):

## What
One sentence — what this PR does.

## Why
One sentence — the motivation or problem it solves.

## Changes
Bullet list of concrete changes: files modified, features added, bugs fixed. Max 8 bullets. Use backticks for file names.

## Testing
How to verify this works. Be specific (manual steps, commands, what to observe).

## Notes
Any caveats, follow-ups, or things reviewers should know. If none, write "None."

Output ONLY valid JSON with two keys: "title" (string) and "body" (string).
No markdown wrapper, no explanation — raw JSON only."""


def latest_replay() -> str:
    if not REPLAYS_DIR.exists():
        return ""
    files = sorted(REPLAYS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return ""
    return files[0].read_text()


def git_diff(repo_path: str) -> str:
    try:
        # staged + unstaged changes vs HEAD
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=15
        )
        diff = result.stdout
        if not diff.strip():
            # try diff against main/master
            for base in ("main", "master", "origin/main", "origin/master"):
                result = subprocess.run(
                    ["git", "diff", base],
                    cwd=repo_path, capture_output=True, text=True, timeout=15
                )
                diff = result.stdout
                if diff.strip():
                    break
        if not diff.strip():
            # fallback: show list of changed files
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            diff = result.stdout
        return diff[:MAX_DIFF_CHARS]
    except Exception:
        return ""


def changed_files(repo_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        files = result.stdout.strip()
        if not files:
            for base in ("main", "master", "origin/main", "origin/master"):
                result = subprocess.run(
                    ["git", "diff", "--name-only", base],
                    cwd=repo_path, capture_output=True, text=True, timeout=10
                )
                files = result.stdout.strip()
                if files:
                    break
        return files
    except Exception:
        return ""


def generate(replay: str, diff: str) -> dict:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    prompt = PROMPT.format(replay=replay[:6000], diff=diff, diff_chars=MAX_DIFF_CHARS)
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
    text = json.loads(resp["body"].read())["content"][0]["text"].strip()
    # strip markdown code fences if model wrapped it
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def main():
    repo_path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

    replay = latest_replay()
    diff   = git_diff(repo_path)

    if not replay and not diff:
        print(json.dumps({"error": "No session replay and no git diff found."}))
        sys.exit(1)

    if not replay:
        replay = "No session replay available."
    if not diff:
        diff = "No git diff available."

    result = generate(replay, diff)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
