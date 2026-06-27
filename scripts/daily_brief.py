#!/usr/bin/env python3
"""
Daily brief — runs at login/9am, writes a signal file the voice-menubar
overlay picks up and displays automatically.

Collects:
  - Open PRs across configured repos (gh CLI)
  - Yesterday's session count + pending items from last replay
  - Any weekly retro saved today (Mondays)

Writes: ~/.claude/daily-brief-signal.json
The voice-menubar _signal_poller reads this and shows it in the overlay.
"""
import json, os, subprocess, sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

REPOS_FILE   = Path.home() / ".claude" / "daily-brief-repos.json"
REPLAYS_DIR  = Path.home() / ".claude" / "session-replays"
SIGNAL_FILE  = Path.home() / ".claude" / "daily-brief-signal.json"

# Default repo dirs to scan — override by creating daily-brief-repos.json
DEFAULT_REPO_DIRS = [
    str(Path.home() / "Desktop" / "CLG" / "catalog"),
    str(Path.home() / "Desktop" / "CLG" / "supply-frontend"),
    str(Path.home() / "Desktop" / "CLG" / "gygadmin"),
]


def load_repos() -> list[str]:
    if REPOS_FILE.exists():
        try:
            return json.loads(REPOS_FILE.read_text()).get("repos", DEFAULT_REPO_DIRS)
        except Exception:
            pass
    return DEFAULT_REPO_DIRS


def get_remote_slug(repo_dir: str) -> Optional[str]:
    r = subprocess.run(
        ["git", "-C", repo_dir, "remote", "get-url", "origin"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return None
    url = r.stdout.strip()
    # git@github.com:org/repo.git  or  https://github.com/org/repo.git
    slug = url.replace("git@github.com:", "").replace("https://github.com/", "").removesuffix(".git")
    return slug


def fetch_prs(repo_dir: str) -> list[dict]:
    slug = get_remote_slug(repo_dir)
    if not slug:
        return []
    r = subprocess.run(
        ["gh", "pr", "list", "--repo", slug, "--author", "@me",
         "--limit", "10", "--json", "number,title,isDraft,reviewDecision,url"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    try:
        return json.loads(r.stdout)
    except Exception:
        return []


def format_pr(pr: dict, repo_name: str) -> str:
    status = ""
    if pr.get("isDraft"):
        status = "draft"
    elif pr.get("reviewDecision") == "APPROVED":
        status = "✓ approved"
    elif pr.get("reviewDecision") == "CHANGES_REQUESTED":
        status = "✗ changes requested"
    elif pr.get("reviewDecision") == "REVIEW_REQUIRED":
        status = "⏳ review needed"
    title = pr["title"][:60] + ("…" if len(pr["title"]) > 60 else "")
    return f"  #{pr['number']} {title} [{status}] ({repo_name})"


def get_yesterday_sessions() -> tuple[int, list[str]]:
    """Count yesterday's sessions and extract pending items from the last one."""
    yesterday = datetime.now() - timedelta(days=1)
    count = 0
    pending = []
    last_replay = None

    if not REPLAYS_DIR.exists():
        return 0, []

    for f in sorted(REPLAYS_DIR.glob("*.md"), reverse=True):
        if "_weekly" in f.name or "_ondemand" in f.name:
            continue
        try:
            date_str = f.stem[:16]
            file_dt  = datetime.strptime(date_str, "%Y-%m-%d_%H-%M")
            if file_dt.date() == yesterday.date():
                count += 1
                if last_replay is None:
                    last_replay = f
        except Exception:
            continue

    if last_replay:
        text = last_replay.read_text()
        # Extract "Pending / Next Steps" section
        in_section = False
        for line in text.splitlines():
            if "pending" in line.lower() or "next step" in line.lower() or "remaining" in line.lower():
                in_section = True
                continue
            if in_section:
                if line.startswith("#"):
                    break
                if line.strip().startswith("-") or line.strip().startswith("*"):
                    item = line.strip().lstrip("-*").strip()
                    if item and "none" not in item.lower() and "fully achieved" not in item.lower():
                        pending.append(item[:80])
                if len(pending) >= 4:
                    break

    return count, pending


def build_brief() -> str:
    today = datetime.now()
    lines = [f"**Good morning — {today.strftime('%A, %b %d')}**\n"]

    # Open PRs
    repos = load_repos()
    all_prs = []
    for repo_dir in repos:
        if not Path(repo_dir).exists():
            continue
        repo_name = Path(repo_dir).name
        prs = fetch_prs(repo_dir)
        for pr in prs:
            all_prs.append((pr, repo_name))

    if all_prs:
        lines.append(f"**{len(all_prs)} open PR(s):**")
        for pr, repo_name in all_prs:
            lines.append(format_pr(pr, repo_name))
        lines.append("")
    else:
        lines.append("No open PRs. Clean slate.")
        lines.append("")

    # Yesterday's sessions
    session_count, pending = get_yesterday_sessions()
    if session_count > 0:
        lines.append(f"**Yesterday:** {session_count} session(s)")
        if pending:
            lines.append("Carried over:")
            for item in pending:
                lines.append(f"  • {item}")
    else:
        lines.append("No sessions yesterday.")
    lines.append("")

    # Monday: nudge for weekly retro
    if today.weekday() == 0:
        lines.append("_It's Monday — run `/weekly` to see last week's retro._")

    return "\n".join(lines)


def main():
    dry_run = "--dry-run" in sys.argv

    brief = build_brief()

    if dry_run:
        print(brief)
        return

    SIGNAL_FILE.write_text(json.dumps({
        "type":    "daily_brief",
        "content": brief,
        "ts":      datetime.now().isoformat(),
    }))
    print(f"Daily brief written to {SIGNAL_FILE}")


if __name__ == "__main__":
    main()
