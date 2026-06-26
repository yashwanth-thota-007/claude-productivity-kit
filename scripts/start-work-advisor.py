#!/usr/bin/env python3
"""
UserPromptSubmit hook — fires before every LLM call.
Injects a worktree suggestion block into the system prompt when:
  1. We're inside a git repo
  2. The session has no active worktree yet (CLAUDE_WORKTREE env not set)
  3. The user's first prompt looks like task-start intent (not a question/chat)
  4. Other sessions are active on the same repo (collision risk)

Output format expected by Claude Code hook: JSON with systemPrompt key.
"""
import json, os, subprocess, sys
from pathlib import Path

REGISTRY = Path.home() / ".claude" / "session-registry.json"

TASK_KEYWORDS = (
    "implement", "add", "build", "fix", "refactor", "create", "update",
    "migrate", "write", "set up", "setup", "integrate", "replace", "remove",
    "feat", "feature", "bug", "patch", "change", "convert", "move", "extract",
)


def is_task_intent(prompt: str) -> bool:
    p = prompt.lower().strip()
    return any(p.startswith(kw) or f" {kw} " in p for kw in TASK_KEYWORDS)


def in_git_repo() -> bool:
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0


def repo_root() -> str:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def current_branch() -> str:
    r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def active_sessions_for_repo(repo: str) -> list:
    if not REGISTRY.exists():
        return []
    with open(REGISTRY) as f:
        data = json.load(f)
    return [s for s in data.get("sessions", []) if s.get("repo") == repo and Path(s["worktree"]).exists()]


def already_in_worktree() -> bool:
    # Claude Code sets this env when inside a worktree session
    return bool(os.environ.get("CLAUDE_WORKTREE") or os.environ.get("GIT_DIR"))


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = hook_input.get("prompt", "")

    # Only advise on task-intent prompts
    if not is_task_intent(prompt):
        sys.exit(0)

    if already_in_worktree():
        sys.exit(0)

    if not in_git_repo():
        sys.exit(0)

    repo = repo_root()
    branch = current_branch()
    sessions = active_sessions_for_repo(repo)

    collision_block = ""
    if sessions:
        session_list = "\n".join(
            f"  - [{s['id']}] branch={s['branch']}  task={s['task']}" for s in sessions
        )
        collision_block = f"""
⚠️  ACTIVE SESSIONS on this repo:
{session_list}

Working on main branch '{branch}' risks conflicts with the above sessions.
"""

    advice = f"""
---
[WORK ISOLATION ADVISOR]
{collision_block}
You are about to start what looks like a development task.
Consider using a git worktree for isolation:
  → Run /start-work to create a dedicated worktree and branch for this task.

This keeps parallel sessions conflict-free and makes PRs easier.
If this is exploratory or read-only work, you can safely ignore this.
---
"""

    output = {"additionalSystemPrompt": advice.strip()}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
