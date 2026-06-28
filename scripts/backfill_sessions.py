#!/usr/bin/env python3
"""
One-time backfill — indexes all existing session replays into ~/.claude/sessions.db
and injects Obsidian [[wikilinks]] into each replay file.

Usage:
  python3 ~/.claude/scripts/backfill_sessions.py
  python3 ~/.claude/scripts/backfill_sessions.py --dry-run   # report only, no writes
"""
import sys
from pathlib import Path
from datetime import datetime

REPLAYS_DIR = Path.home() / ".claude" / "session-replays"

sys.path.insert(0, str(Path(__file__).parent))
from db import personal_db
from embed import embed
from index_session import parse_replay, already_indexed, index_file, find_similar, inject_wikilinks


def main():
    dry_run = "--dry-run" in sys.argv

    if not REPLAYS_DIR.exists():
        print(f"No session replays found at {REPLAYS_DIR}")
        return

    files = sorted(
        [f for f in REPLAYS_DIR.glob("*.md")
         if "_weekly" not in f.name and "_ondemand" not in f.name],
        key=lambda f: f.stat().st_mtime,
    )

    if not files:
        print("No session replay files to backfill.")
        return

    print(f"Found {len(files)} session replays. {'(dry-run)' if dry_run else 'Indexing...'}\n")

    conn = personal_db()
    indexed = 0
    skipped = 0

    for i, path in enumerate(files, 1):
        if already_indexed(conn, path.name):
            print(f"  [{i}/{len(files)}] skip (already indexed): {path.name}")
            skipped += 1
            continue

        try:
            if dry_run:
                print(f"  [{i}/{len(files)}] would index: {path.name}")
                indexed += 1
                continue

            vec = index_file(conn, path)
            similar = find_similar(conn, vec, path.name)
            inject_wikilinks(path, similar)
            link_count = len(similar)
            print(f"  [{i}/{len(files)}] indexed: {path.name} → {link_count} link(s)")
            indexed += 1
        except Exception as e:
            print(f"  [{i}/{len(files)}] ERROR {path.name}: {e}")

    print(f"\nDone. Indexed: {indexed}, Skipped: {skipped}")
    if not dry_run and indexed > 0:
        print(f"\nOpen {REPLAYS_DIR} as an Obsidian vault to explore the graph.")


if __name__ == "__main__":
    main()
