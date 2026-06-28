#!/usr/bin/env python3
"""
PreToolUse hook — nudges user to run /code-complete before committing
if the session had a coding goal and the diff has non-test file changes.

Soft nudge only — commit always proceeds.
"""
import json, sys, subprocess
from pathlib import Path

CONTRACTS_DIR = Path.home() / ".claude" / "session-contracts"
SESSION_ID_FILE = Path.home() / ".claude" / "active-session-id"

CODING_KEYWORDS = [
    "implement", "build", "add", "fix", "refactor", "create", "write",
    "migrate", "integrate", "update", "replace", "remove", "set up",
]

TEST_PATTERNS = ["test", "spec", "tests/", "__tests__/", ".test.", ".spec."]


def load_contract() -> dict:
    if not SESSION_ID_FILE.exists():
        return {}
    session_id = SESSION_ID_FILE.read_text().strip()
    if not session_id:
        return {}
    path = CONTRACTS_DIR / f"{session_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def has_non_test_changes() -> bool:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=5,
        )
        staged = result.stdout.strip().splitlines()
        if not staged:
            result = subprocess.run(
                ["git", "diff", "HEAD", "--name-only"],
                capture_output=True, text=True, timeout=5,
            )
            staged = result.stdout.strip().splitlines()
        return any(
            not any(p in f.lower() for p in TEST_PATTERNS)
            for f in staged
        )
    except Exception:
        return False


def is_coding_task(contract: dict) -> bool:
    if contract.get("_skipped"):
        return False
    product = contract.get("product", "").lower()
    return any(kw in product for kw in CODING_KEYWORDS)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    command = hook_input.get("tool_input", {}).get("command", "")
    if "git commit" not in command:
        sys.exit(0)

    contract = load_contract()
    if not contract or not is_coding_task(contract):
        sys.exit(0)

    if not has_non_test_changes():
        sys.exit(0)

    title = contract.get("session_title", "this session")
    product = contract.get("product", "")

    print(json.dumps({
        "systemMessage": (
            f"Session goal: \"{product}\" ({title})\n"
            f"You're about to commit — did you run /code-complete?\n"
            f"It runs tests + code review and takes ~1 min. Skip with next commit if already done."
        )
    }))


if __name__ == "__main__":
    main()
