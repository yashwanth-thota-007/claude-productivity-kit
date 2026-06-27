#!/usr/bin/env python3
"""
Session search — called by /search-sessions command.

Searches session replays by keyword, date, or semantic query.
Usage:
  python3 ~/.claude/scripts/search_sessions.py "youtube"
  python3 ~/.claude/scripts/search_sessions.py "last tuesday"
  python3 ~/.claude/scripts/search_sessions.py --date 2026-06-27
  python3 ~/.claude/scripts/search_sessions.py --last 3   (last N sessions)
"""
import sys, re, json, os, boto3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID   = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
)

WEEKDAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]


def parse_date_query(query: str) -> Optional[datetime]:
    q = query.lower().strip()
    today = datetime.now()

    if q == "today":
        return today.replace(hour=0, minute=0, second=0)
    if q == "yesterday":
        return (today - timedelta(days=1)).replace(hour=0, minute=0, second=0)

    for i, day in enumerate(WEEKDAYS):
        if day in q:
            days_ago = (today.weekday() - i) % 7
            if days_ago == 0:
                days_ago = 7
            return (today - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)

    try:
        return datetime.strptime(query.strip(), "%Y-%m-%d")
    except ValueError:
        pass
    return None


def load_all_replays() -> list[dict]:
    replays = []
    if not REPLAYS_DIR.exists():
        return replays
    for f in sorted(REPLAYS_DIR.glob("*.md"), reverse=True):
        try:
            date_str = f.stem[:16]
            file_dt  = datetime.strptime(date_str, "%Y-%m-%d_%H-%M")
            replays.append({"file": f.name, "date": file_dt, "path": f, "text": f.read_text()})
        except Exception:
            continue
    return replays


def keyword_search(replays: list[dict], query: str) -> list[dict]:
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results = []
    for r in replays:
        if pattern.search(r["text"]):
            # Extract snippet around first match
            m = pattern.search(r["text"])
            start = max(0, m.start() - 100)
            end   = min(len(r["text"]), m.end() + 200)
            snippet = r["text"][start:end].replace("\n", " ").strip()
            results.append({**r, "snippet": f"…{snippet}…"})
    return results


def date_search(replays: list[dict], target: datetime) -> list[dict]:
    return [r for r in replays
            if r["date"].date() == target.date()]


def semantic_search(replays: list[dict], query: str) -> list[dict]:
    """Ask Haiku which sessions are most relevant to the query."""
    if not replays:
        return []

    index = "\n".join(
        f"{i+1}. [{r['date'].strftime('%a %b %d')}] {r['file']}: {r['text'][:300].replace(chr(10),' ')}"
        for i, r in enumerate(replays[:30])
    )

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": (
            f"Given this list of session summaries, which ones are most relevant to: \"{query}\"\n\n"
            f"{index}\n\n"
            "Reply with ONLY a comma-separated list of numbers (e.g. 1,3,7). "
            "Pick up to 5 most relevant. If none are relevant, reply: none"
        )}],
    }
    resp = client.invoke_model(
        modelId=MODEL_ID, body=json.dumps(body),
        contentType="application/json", accept="application/json",
    )
    answer = json.loads(resp["body"].read())["content"][0]["text"].strip()
    if answer.lower() == "none":
        return []
    indices = []
    for part in answer.split(","):
        try:
            indices.append(int(part.strip()) - 1)
        except ValueError:
            pass
    return [replays[i] for i in indices if 0 <= i < len(replays)]


def format_results(results: list[dict], mode: str) -> str:
    if not results:
        return "No matching sessions found."

    lines = [f"**{len(results)} session(s) found:**\n"]
    for r in results:
        date_str = r["date"].strftime("%a %b %d, %Y %H:%M")
        lines.append(f"### {date_str}")
        lines.append(f"`{r['file']}`\n")
        # Show first meaningful section of replay
        text = r["text"]
        if "snippet" in r:
            lines.append(f"_{r['snippet']}_\n")
        else:
            # Show first 400 chars after the header
            body = re.sub(r"^#.*\n(\*\*.*\n)*", "", text, flags=re.MULTILINE).strip()
            lines.append(f"{body[:400]}{'…' if len(body) > 400 else ''}\n")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: search_sessions.py <query>")
        print("       search_sessions.py --date 2026-06-27")
        print("       search_sessions.py --last 5")
        sys.exit(1)

    replays = load_all_replays()
    if not replays:
        print(f"No session replays found in {REPLAYS_DIR}")
        sys.exit(0)

    # --last N
    if args[0] == "--last":
        n = int(args[1]) if len(args) > 1 else 5
        results = replays[:n]
        print(format_results(results, "last"))
        return

    # --date YYYY-MM-DD
    if args[0] == "--date":
        query = args[1] if len(args) > 1 else ""
        target = parse_date_query(query)
        if not target:
            print(f"Could not parse date: {query}")
            sys.exit(1)
        results = date_search(replays, target)
        print(format_results(results, "date"))
        return

    query = " ".join(args)

    # Try natural language date first
    target = parse_date_query(query)
    if target:
        results = date_search(replays, target)
        print(format_results(results, "date"))
        return

    # Keyword search first (fast, no API cost)
    results = keyword_search(replays, query)
    if results:
        print(format_results(results, "keyword"))
        return

    # Fall back to semantic search via Haiku
    print(f"_No exact matches for '{query}' — trying semantic search…_\n")
    try:
        results = semantic_search(replays, query)
        print(format_results(results, "semantic"))
    except Exception as e:
        print(f"Semantic search failed: {e}")


if __name__ == "__main__":
    main()
