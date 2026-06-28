#!/usr/bin/env python3
"""
SessionStart hook — bootstrap project mental model from project docs on first visit.

If <project-root>/.claude/mental-model.db does not exist:
  - Embeds prime-results.md, .claude/docs/*.md, and README.md as seed entries
  - Stores in mental-model.db so --query works from the very first prompt
  - Outputs a systemMessage confirming what was indexed

Subsequent sessions skip this (DB already exists).
"""
import json, sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))


def _find_project_root(cwd: Path) -> Optional[Path]:
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists() or (parent / ".claude").exists():
            return parent
        if parent == parent.parent:
            break
    return None


def _collect_docs(project_root: Path) -> list:
    """Return [(title, content)] from prime-results, .claude/docs/, and README."""
    docs = []

    prime = project_root / ".claude" / "prime-results.md"
    if prime.exists():
        docs.append(("prime-results", prime.read_text()))

    docs_dir = project_root / ".claude" / "docs"
    if docs_dir.exists():
        for f in sorted(docs_dir.glob("*.md")):
            docs.append((f.stem, f.read_text()))

    # README fallback only if no .claude docs found
    if not docs:
        for name in ["README.md", "README.rst", "README"]:
            readme = project_root / name
            if readme.exists():
                docs.append(("readme", readme.read_text()))
                break

    return docs


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cwd_str = hook_input.get("cwd", "")
    if not cwd_str:
        sys.exit(0)

    cwd = Path(cwd_str)
    project_root = _find_project_root(cwd)
    if not project_root:
        sys.exit(0)

    db_path = project_root / ".claude" / "mental-model.db"
    if db_path.exists():
        sys.exit(0)

    docs = _collect_docs(project_root)
    if not docs:
        sys.exit(0)

    from db import project_db, vec_to_json
    from embed import embed

    conn = project_db(project_root)

    for title, content in docs:
        vec = vec_to_json(embed(f"{title}\n\n{content[:2000]}"))
        summary = content[:500].replace("\n", " ").strip()
        conn.execute(
            "INSERT INTO mental_model (session_id, file_name, date, title, summary, embedding) "
            "VALUES ('bootstrap', ?, datetime('now'), ?, ?, ?)",
            (f"{title}.md", title, summary, vec),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO mental_model_fts (rowid, session_id, file_name, date, title, content) "
            "VALUES (?, 'bootstrap', ?, datetime('now'), ?, ?)",
            (row_id, f"{title}.md", title, content[:8000]),
        )

    conn.commit()

    doc_names = ", ".join(t for t, _ in docs)
    print(json.dumps({
        "systemMessage": f"🧠 Project mental model initialized for {project_root.name} ({len(docs)} doc(s): {doc_names})"
    }))


if __name__ == "__main__":
    main()
