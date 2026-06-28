#!/usr/bin/env python3
"""
Project-level mental model — per-project session knowledge base.

--update  (called by Stop hook via session-replay.py)
    Reads the just-written session replay, detects the project working dir,
    embeds + stores in <project>/.claude/mental-model.db.

--query   (called by UserPromptSubmit hook via session-contract.py)
    Reads current prompt + working dir, queries mental-model.db for top-5
    relevant context, prints JSON for additionalSystemPrompt injection.

Usage:
    python3 project_mental_model.py --update <replay_file> <cwd>
    python3 project_mental_model.py --query  <prompt_text> <cwd>
"""
import sys, re, json
from pathlib import Path
from datetime import datetime
from typing import Optional

SIMILARITY_THRESHOLD = 0.30
TOP_N = 5

sys.path.insert(0, str(Path(__file__).parent))
from db import project_db, vec_to_json, cosine_distance
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


def _find_project_root(cwd: Path) -> Optional[Path]:
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists() or (parent / ".claude").exists():
            return parent
        if parent == parent.parent:
            break
    return None


def update(replay_path: Path, cwd: Path):
    if not replay_path.exists():
        return
    project_root = _find_project_root(cwd)
    if not project_root:
        return

    conn = project_db(project_root)
    session_id, date, title, content = parse_replay(replay_path)

    vec = embed(f"{title}\n\n{content[:2000]}")
    vec_json = vec_to_json(vec)
    summary = content[:500].replace("\n", " ").strip()

    conn.execute("DELETE FROM mental_model WHERE session_id = ?", (session_id,))
    conn.execute(
        "INSERT INTO mental_model (session_id, file_name, date, title, summary, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, replay_path.name, date, title, summary, vec_json),
    )
    row_id = conn.execute("SELECT id FROM mental_model WHERE session_id = ?", (session_id,)).fetchone()[0]
    conn.execute("DELETE FROM mental_model_fts WHERE session_id = ?", (session_id,))
    conn.execute(
        "INSERT INTO mental_model_fts (rowid, session_id, file_name, date, title, content) VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, session_id, replay_path.name, date, title, content[:8000]),
    )
    conn.commit()


def query(prompt: str, cwd: Path) -> str:
    project_root = _find_project_root(cwd)
    if not project_root:
        return ""

    db_path = project_root / ".claude" / "mental-model.db"
    if not db_path.exists():
        return ""

    conn = project_db(project_root)
    vec = embed(prompt[:500])

    rows = conn.execute(
        "SELECT date, title, summary, embedding FROM mental_model WHERE embedding IS NOT NULL"
    ).fetchall()

    scored = []
    for row in rows:
        dist = cosine_distance(vec, row["embedding"])
        if dist <= SIMILARITY_THRESHOLD:
            scored.append((dist, row["date"], row["title"], row["summary"]))

    scored.sort(key=lambda x: x[0])
    results = [f"- [{date}] {title}: {(summary or '')[:120]}" for _, date, title, summary in scored[:TOP_N]]

    if not results:
        return ""
    return "## Project Mental Model (relevant past sessions)\n" + "\n".join(results)


def main():
    if len(sys.argv) < 3:
        print("Usage: project_mental_model.py --update <replay_file> <cwd>")
        print("       project_mental_model.py --query  <prompt> <cwd>")
        sys.exit(1)

    mode = sys.argv[1]
    cwd = Path(sys.argv[-1])

    if mode == "--update":
        update(Path(sys.argv[2]), cwd)
    elif mode == "--query":
        context = query(sys.argv[2], cwd)
        if context:
            print(json.dumps({"additionalSystemPrompt": context}))
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
