#!/usr/bin/env python3
"""
PostToolUse hook — auto-indexes knowledge from fetch/WebSearch tool results.

Fires after every fetch or WebSearch tool call. Extracts facts via Haiku
and stores in ~/.claude/knowledge.db.

For code-heavy content, uses a lightweight code-extraction path that pulls
function signatures, class names, and usage patterns rather than skipping.
For prose content, uses the full Haiku fact-extraction path.
"""
import json, re, sys
from pathlib import Path

MIN_CONTENT_LEN = 200
MAX_CONTENT_LEN = 8000

sys.path.insert(0, str(Path(__file__).parent))


def _is_code_heavy(lines: list) -> bool:
    code_lines = sum(
        1 for l in lines[:20]
        if l.strip().startswith(("{", "[", "//", "#!", "import ", "def ", "function ", "class ", "export "))
        or re.match(r"^\s*(const|let|var|type|interface|fn |pub fn |async fn )\s", l)
    )
    return code_lines > 6


def _extract_code_facts(content: str, source_url: str) -> list:
    """Pull structured facts from code without LLM — function/class names + doc comments."""
    facts = []
    lines = content.splitlines()

    # Python / JS / TS / Rust function/class patterns
    patterns = [
        (r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]{0,80})\)", "function"),
        (r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)", "class"),
        (r"^def\s+(\w+)\s*\(([^)]{0,80})\)", "function"),
        (r"^class\s+(\w+)[:(]", "class"),
        (r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(([^)]{0,80})\)", "function"),
        (r"^(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]{0,60})\)\s*=>", "function"),
    ]

    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat, kind in patterns:
            m = re.match(pat, stripped)
            if m:
                name = m.group(1)
                # Try to grab preceding docstring/comment
                comment = ""
                for j in range(max(0, i-3), i):
                    cl = lines[j].strip()
                    if cl.startswith(("/*", "*", "//", '"""', "'''", "#")):
                        comment = cl.lstrip("/*#\"' ").rstrip("*/\"'").strip()
                        if comment:
                            break
                sig = stripped[:100]
                fact = f"`{name}` ({kind}) in {source_url or 'fetched code'}: {sig}"
                if comment:
                    fact += f" — {comment}"
                facts.append(fact)
                if len(facts) >= 10:
                    return facts
                break

    # If too few function facts, also grab any README-style headings as context
    if len(facts) < 3:
        for line in lines:
            if line.startswith("# ") or line.startswith("## "):
                heading = line.lstrip("# ").strip()
                if len(heading) > 8:
                    facts.append(f"Documentation section from {source_url or 'source'}: {heading}")
                if len(facts) >= 5:
                    break

    return facts


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("fetch", "WebFetch", "WebSearch", "mcp__fetch__fetch"):
        sys.exit(0)

    session_id = hook_input.get("session_id", "")

    tool_response = hook_input.get("tool_response", {})
    content = ""
    source_url = ""

    if isinstance(tool_response, dict):
        content = tool_response.get("content", "") or tool_response.get("text", "")
        source_url = tool_response.get("url", "") or hook_input.get("tool_input", {}).get("url", "")
    elif isinstance(tool_response, str):
        content = tool_response

    if not source_url:
        tool_input = hook_input.get("tool_input", {})
        source_url = tool_input.get("url", "") or tool_input.get("query", "")

    if not content or len(content) < MIN_CONTENT_LEN:
        sys.exit(0)

    lines = content.splitlines()
    is_code = _is_code_heavy(lines)

    from knowledge import extract_facts, store

    if is_code:
        facts = _extract_code_facts(content[:MAX_CONTENT_LEN], source_url)
        source_type = "code"
    else:
        facts = extract_facts(content[:MAX_CONTENT_LEN], source_url)
        source_type = "web"

    if not facts:
        sys.exit(0)

    n = store(facts, source_url=source_url, source_type=source_type, session_id=session_id)
    if n > 0:
        icon = "💻" if is_code else "📚"
        print(json.dumps({"systemMessage": f"{icon} Indexed {n} fact(s) from {source_url or 'fetch result'}"}))


if __name__ == "__main__":
    main()
