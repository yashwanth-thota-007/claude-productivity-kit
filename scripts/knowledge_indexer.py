#!/usr/bin/env python3
"""
PostToolUse hook — auto-indexes knowledge from fetch/WebSearch tool results.

Fires after every fetch or WebSearch tool call. Extracts facts via Haiku
and stores in ~/.claude/knowledge.db. Fast-exits if content is code/binary
or under the minimum length threshold.
"""
import json, sys
from pathlib import Path

MIN_CONTENT_LEN = 200   # skip trivial responses
MAX_CONTENT_LEN = 8000  # trim before sending to Haiku

sys.path.insert(0, str(Path(__file__).parent))


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("fetch", "WebFetch", "WebSearch", "mcp__fetch__fetch"):
        sys.exit(0)

    session_id = hook_input.get("session_id", "")

    # Extract content from tool result
    tool_response = hook_input.get("tool_response", {})
    content = ""
    source_url = ""

    if isinstance(tool_response, dict):
        # fetch/WebFetch returns {url, content}
        content = tool_response.get("content", "") or tool_response.get("text", "")
        source_url = tool_response.get("url", "") or hook_input.get("tool_input", {}).get("url", "")
    elif isinstance(tool_response, str):
        content = tool_response

    # Also check tool_input for URL
    if not source_url:
        tool_input = hook_input.get("tool_input", {})
        source_url = tool_input.get("url", "") or tool_input.get("query", "")

    if not content or len(content) < MIN_CONTENT_LEN:
        sys.exit(0)

    # Skip if it looks like code/JSON/binary rather than readable prose
    lines = content.splitlines()
    code_lines = sum(1 for l in lines[:20] if l.strip().startswith(("{", "[", "<", "//", "#!", "import", "def ", "function")))
    if code_lines > 8:
        sys.exit(0)

    from knowledge import extract_facts, store
    facts = extract_facts(content[:MAX_CONTENT_LEN], source_url)
    if not facts:
        sys.exit(0)

    n = store(facts, source_url=source_url, source_type="web", session_id=session_id)
    if n > 0:
        print(json.dumps({"systemMessage": f"📚 Indexed {n} fact(s) from {source_url or 'fetch result'}"}))


if __name__ == "__main__":
    main()
