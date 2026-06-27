#!/usr/bin/env python3
"""Session registry for Claude Code multi-session worktree management."""
import json, argparse
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_PATH = Path.home() / ".claude" / "session-registry.json"


def load_registry():
    if not REGISTRY_PATH.exists():
        return {"sessions": []}
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def save_registry(data):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_stale(registry):
    active = [s for s in registry["sessions"] if Path(s["worktree"]).exists()]
    removed = len(registry["sessions"]) - len(active)
    registry["sessions"] = active
    return removed


def register(repo, branch, worktree, task, session_id=None):
    registry = load_registry()
    cleanup_stale(registry)
    entry = {
        "id": session_id or f"{Path(repo).name}-{branch.split('/')[-1]}-{datetime.now().strftime('%H%M%S')}",
        "repo": str(Path(repo).resolve()),
        "branch": branch,
        "worktree": worktree,
        "task": task,
        "started": datetime.now(timezone.utc).isoformat(),
    }
    registry["sessions"].append(entry)
    save_registry(registry)
    print(json.dumps(entry))


def unregister(session_id=None, worktree=None):
    registry = load_registry()
    before = len(registry["sessions"])
    if session_id:
        registry["sessions"] = [s for s in registry["sessions"] if s["id"] != session_id]
    elif worktree:
        registry["sessions"] = [s for s in registry["sessions"] if s["worktree"] != worktree]
    removed = before - len(registry["sessions"])
    save_registry(registry)
    print(f"Removed {removed} session(s)")


def list_sessions(repo=None):
    registry = load_registry()
    cleanup_stale(registry)
    save_registry(registry)
    sessions = registry["sessions"]
    if repo:
        repo_resolved = str(Path(repo).resolve())
        sessions = [s for s in sessions if s["repo"] == repo_resolved]
    print(json.dumps(sessions, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Claude Code session registry")
    sub = parser.add_subparsers(dest="cmd")

    r = sub.add_parser("register")
    r.add_argument("--repo", required=True)
    r.add_argument("--branch", required=True)
    r.add_argument("--worktree", required=True)
    r.add_argument("--task", required=True)
    r.add_argument("--id")

    u = sub.add_parser("unregister")
    u.add_argument("--id")
    u.add_argument("--worktree")

    ls = sub.add_parser("list")
    ls.add_argument("--repo")

    args = parser.parse_args()

    if args.cmd == "register":
        register(args.repo, args.branch, args.worktree, args.task, args.id)
    elif args.cmd == "unregister":
        unregister(args.id, getattr(args, "worktree", None))
    elif args.cmd == "list":
        list_sessions(getattr(args, "repo", None))
    else:
        parser.print_help()
