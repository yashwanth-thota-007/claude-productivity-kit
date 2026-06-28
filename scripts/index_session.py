#!/usr/bin/env python3
"""
Index a session replay into ~/.claude/sessions.db and inject Obsidian wikilinks.

Called by session-replay.py after writing the replay file:
    python3 ~/.claude/scripts/index_session.py <replay_file_path>

Steps:
  1. Embed title + first 2000 chars of replay
  2. Upsert into sessions.db (FTS5 + JSON embedding)
  3. Find top-5 similar sessions (cosine distance ≤ 0.25)
  4. Inject "## Related Sessions" [[wikilinks]] block into the replay file
"""
import sys, re
from pathlib import Path
from datetime import datetime

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"
SIMILARITY_THRESHOLD = 0.25
TOP_N = 5

sys.path.insert(0, str(Path(__file__).parent))
from db import personal_db, vec_to_json, cosine_distance
from embed import embed


def parse_replay(path: Path) -> tuple:
    text = path.read_text()
    title_match = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem
    try:
        date = datetime.strptime(path.stem[:16], "%Y-%m-%d_%H-%M").strftime("%Y-%m-%d %H:%M")
    except Exception:
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
    session_id = path.stem[17:25] if len(path.stem) > 17 else path.stem
    content = re.sub(r"\n## Related Sessions\n.*?(?=\n## |\Z)", "", text, flags=re.DOTALL).strip()
    return session_id, date, title, content


def already_indexed(conn, file_name: str) -> bool:
    row = conn.execute("SELECT id FROM sessions WHERE file_name = ?", (file_name,)).fetchone()
    return row is not None


def index_file(conn, path: Path) -> list:
    session_id, date, title, content = parse_replay(path)
    embed_text = f"{title}\n\n{content[:2000]}"
    vec = embed(embed_text)
    vec_json = vec_to_json(vec)

    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, file_name, date, title, embedding) VALUES (?, ?, ?, ?, ?)",
        (session_id, path.name, date, title, vec_json),
    )
    row_id = conn.execute("SELECT id FROM sessions WHERE file_name = ?", (path.name,)).fetchone()[0]

    conn.execute("DELETE FROM sessions_fts WHERE session_id = ?", (session_id,))
    conn.execute(
        "INSERT INTO sessions_fts (rowid, session_id, file_name, date, title, content) VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, session_id, path.name, date, title, content[:8000]),
    )
    conn.commit()
    return vec


def find_similar(conn, vec: list, exclude_file: str) -> list:
    rows = conn.execute(
        "SELECT file_name, title, date, embedding FROM sessions WHERE file_name != ? AND embedding IS NOT NULL",
        (exclude_file,),
    ).fetchall()

    scored = []
    for row in rows:
        dist = cosine_distance(vec, row["embedding"])
        if dist <= SIMILARITY_THRESHOLD:
            sim = round(1.0 - (dist / 2.0), 2)
            scored.append({"stem": Path(row["file_name"]).stem, "title": row["title"],
                           "date": row["date"], "sim": sim, "dist": dist})

    scored.sort(key=lambda x: x["dist"])
    return scored[:TOP_N]


def inject_wikilinks(path: Path, similar: list):
    if not similar:
        return
    text = path.read_text()
    text = re.sub(r"\n## Related Sessions\n.*?(?=\n## |\Z)", "", text, flags=re.DOTALL).rstrip()
    lines = ["\n\n## Related Sessions"]
    for s in similar:
        lines.append(f"- [[{s['stem']}]] — {s['title']} (sim: {s['sim']})")
    path.write_text(text + "\n".join(lines) + "\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: index_session.py <replay_file_path>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    conn = personal_db()

    if already_indexed(conn, path.name):
        _, _, title, content = parse_replay(path)
        vec = embed(f"{title}\n\n{content[:2000]}")
    else:
        vec = index_file(conn, path)

    similar = find_similar(conn, vec, path.name)
    inject_wikilinks(path, similar)

    if similar:
        print(f"Linked {len(similar)} related sessions: {', '.join(s['stem'] for s in similar)}")


if __name__ == "__main__":
    main()
