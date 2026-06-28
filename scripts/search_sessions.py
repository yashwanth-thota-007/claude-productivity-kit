#!/usr/bin/env python3
"""
Session search — called by /search-sessions command.

Searches session replays by keyword (FTS5), date, or semantic query (local vector).
No API calls — fully local.

Usage:
  python3 ~/.claude/scripts/search_sessions.py "youtube"
  python3 ~/.claude/scripts/search_sessions.py "last tuesday"
  python3 ~/.claude/scripts/search_sessions.py --date 2026-06-27
  python3 ~/.claude/scripts/search_sessions.py --last 3
"""
import sys, re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"
WEEKDAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]

sys.path.insert(0, str(Path(__file__).parent))


def parse_date_query(query: str) -> Optional[datetime]:
    q = query.lower().strip()
    today = datetime.now()
    if q == "today":
        return today.replace(hour=0, minute=0, second=0)
    if q == "yesterday":
        return (today - timedelta(days=1)).replace(hour=0, minute=0, second=0)
    for i, day in enumerate(WEEKDAYS):
        if day in q:
            days_ago = (today.weekday() - i) % 7 or 7
            return (today - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)
    try:
        return datetime.strptime(query.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def fts_search(query: str) -> list:
    from db import personal_db
    conn = personal_db()
    try:
        rows = conn.execute(
            """
            SELECT s.file_name, s.date, s.title,
                   snippet(sessions_fts, 4, '[', ']', '…', 20) AS snip
            FROM sessions_fts
            JOIN sessions s ON sessions_fts.rowid = s.id
            WHERE sessions_fts MATCH ?
            ORDER BY sessions_fts.rank
            LIMIT 10
            """,
            (query,),
        ).fetchall()
    except Exception:
        return []
    results = []
    for row in rows:
        path = REPLAYS_DIR / row["file_name"]
        results.append({"file": row["file_name"], "date": _parse_date(row["date"]),
                         "title": row["title"], "snippet": row["snip"], "path": path})
    return results


def vector_search(query: str) -> list:
    from db import personal_db, cosine_distance
    from embed import embed
    conn = personal_db()
    vec = embed(query)
    rows = conn.execute(
        "SELECT file_name, date, title, embedding FROM sessions WHERE embedding IS NOT NULL"
    ).fetchall()
    scored = []
    for row in rows:
        dist = cosine_distance(vec, row["embedding"])
        if dist <= 0.35:
            sim = round(1.0 - (dist / 2.0), 2)
            scored.append((dist, row["file_name"], row["date"], row["title"], sim))
    scored.sort(key=lambda x: x[0])
    results = []
    for dist, file_name, date, title, sim in scored[:10]:
        path = REPLAYS_DIR / file_name
        results.append({"file": file_name, "date": _parse_date(date), "title": title,
                         "snippet": f"semantic match (sim: {sim})", "path": path})
    return results


def date_search(target: datetime) -> list:
    results = []
    if not REPLAYS_DIR.exists():
        return results
    for f in sorted(REPLAYS_DIR.glob("*.md"), reverse=True):
        try:
            dt = datetime.strptime(f.stem[:16], "%Y-%m-%d_%H-%M")
            if dt.date() == target.date():
                results.append({"file": f.name, "date": dt, "title": f.stem, "path": f})
        except Exception:
            continue
    return results


def last_n(n: int) -> list:
    results = []
    if not REPLAYS_DIR.exists():
        return results
    for f in sorted(REPLAYS_DIR.glob("*.md"), reverse=True)[:n]:
        try:
            dt = datetime.strptime(f.stem[:16], "%Y-%m-%d_%H-%M")
            results.append({"file": f.name, "date": dt, "title": f.stem, "path": f})
        except Exception:
            continue
    return results


def _parse_date(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            pass
    return datetime.now()


def format_results(results: list) -> str:
    if not results:
        return "No matching sessions found."
    lines = [f"**{len(results)} session(s) found:**\n"]
    for r in results:
        date_str = r["date"].strftime("%a %b %d, %Y %H:%M") if isinstance(r["date"], datetime) else str(r["date"])
        title = r.get("title") or r["file"]
        lines.append(f"### {date_str}")
        lines.append(f"`{r['file']}`")
        if r.get("snippet"):
            lines.append(f"_{r['snippet']}_")
        elif r.get("path") and Path(r["path"]).exists():
            body = re.sub(r"^#.*\n(\*\*.*\n)*", "", Path(r["path"]).read_text(),
                          flags=re.MULTILINE).strip()
            lines.append(f"{body[:300]}{'…' if len(body) > 300 else ''}")
        lines.append("")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: search_sessions.py <query>")
        print("       search_sessions.py --date 2026-06-27")
        print("       search_sessions.py --last 5")
        sys.exit(1)

    if args[0] == "--last":
        n = int(args[1]) if len(args) > 1 else 5
        print(format_results(last_n(n)))
        return

    if args[0] == "--date":
        q = args[1] if len(args) > 1 else ""
        target = parse_date_query(q)
        if not target:
            print(f"Could not parse date: {q}")
            sys.exit(1)
        print(format_results(date_search(target)))
        return

    query = " ".join(args)

    # Natural language date
    target = parse_date_query(query)
    if target:
        print(format_results(date_search(target)))
        return

    # FTS5 keyword search
    results = fts_search(query)
    if results:
        print(format_results(results))
        return

    # Local vector fallback — no API call
    print(f"_No exact matches for '{query}' — trying semantic search…_\n")
    results = vector_search(query)
    print(format_results(results))


if __name__ == "__main__":
    main()
