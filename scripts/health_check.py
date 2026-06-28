#!/usr/bin/env python3
"""
/health — checks all kit dependencies and config are in order.
Prints a status table and exits 0 if healthy, 1 if any checks fail.
"""
import sys, os, subprocess, json
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
OK   = "✓"
FAIL = "✗"
WARN = "⚠"

results = []
failed  = 0


def check(label: str, fn):
    global failed
    try:
        status, note = fn()
    except Exception as e:
        status, note = False, str(e)
    icon = OK if status else FAIL
    if not status:
        failed += 1
    results.append((icon, label, note))


def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


# ── CLI tools ────────────────────────────────────────────────────────────────

check("claude CLI", lambda: (
    Path("/opt/homebrew/bin/claude").exists(),
    subprocess.run(["/opt/homebrew/bin/claude","--version"], capture_output=True, text=True).stdout.strip()
))

check("jq", lambda: (
    subprocess.run(["which","jq"], capture_output=True).returncode == 0,
    subprocess.run(["jq","--version"], capture_output=True, text=True).stdout.strip()
))

check("node / npx", lambda: (
    subprocess.run(["which","node"], capture_output=True).returncode == 0,
    subprocess.run(["node","--version"], capture_output=True, text=True).stdout.strip()
))

check("gh CLI", lambda: (
    subprocess.run(["which","gh"], capture_output=True).returncode == 0,
    subprocess.run(["gh","--version"], capture_output=True, text=True).stdout.splitlines()[0] if
    subprocess.run(["which","gh"], capture_output=True).returncode == 0 else "not found"
))

# ── Python packages (voice menubar) ──────────────────────────────────────────

def check_py_pkg(pkg: str):
    rc = subprocess.run(
        ["/opt/homebrew/bin/python3.13", "-c", f"import {pkg}"],
        capture_output=True
    ).returncode
    return rc == 0, "installed" if rc == 0 else "missing — pip install " + pkg

for pkg in ["whisper","rumps","sounddevice","webrtcvad","pyperclip","numpy","mistune","pynput"]:
    check(f"py: {pkg}", lambda p=pkg: check_py_pkg(p))

check("py: boto3", lambda: check_py_pkg("boto3"))
check("py: Quartz", lambda: check_py_pkg("Quartz"))

# ── AWS / Bedrock ────────────────────────────────────────────────────────────

def check_aws():
    profile = os.environ.get("AWS_PROFILE","")
    region  = os.environ.get("AWS_REGION","")
    if not profile:
        return False, "AWS_PROFILE not set"
    rc = subprocess.run(
        ["aws","sts","get-caller-identity","--profile",profile],
        capture_output=True, text=True
    ).returncode
    return rc == 0, f"profile={profile} region={region}" if rc == 0 else f"auth failed for {profile}"

check("AWS credentials", check_aws)

# ── Settings files ────────────────────────────────────────────────────────────

check("settings.json exists", lambda: (
    (CLAUDE_DIR / "settings.json").exists(),
    str(CLAUDE_DIR / "settings.json")
))

def check_settings_keys():
    path = CLAUDE_DIR / "settings.json"
    if not path.exists():
        return False, "settings.json missing"
    cfg = json.loads(path.read_text())
    env = cfg.get("env", {})
    missing = [k for k in ["AWS_PROFILE","AWS_REGION","ANTHROPIC_MODEL"] if k not in env]
    return len(missing) == 0, "all keys present" if not missing else f"missing: {', '.join(missing)}"

check("settings.json keys", check_settings_keys)

check(".env file", lambda: (
    (CLAUDE_DIR / ".env").exists(),
    str(CLAUDE_DIR / ".env")
))

check("mcp.json", lambda: (
    (CLAUDE_DIR / "mcp.json").exists() or (Path.home() / ".mcp.json").exists(),
    "found"
))

# ── LaunchAgents ─────────────────────────────────────────────────────────────

def check_launch_agent(name: str):
    plist = Path.home() / "Library" / "LaunchAgents" / f"{name}.plist"
    if not plist.exists():
        return False, "plist not in ~/Library/LaunchAgents"
    rc, out = run(["launchctl", "list", name])
    running = "PID" in out or rc == 0
    return running, "running" if running else "loaded but not running"

check("LaunchAgent: voice-menubar", lambda: check_launch_agent("com.claude.voice-menubar"))
check("LaunchAgent: standup",       lambda: check_launch_agent("com.claude.standup"))

# ── Session data ──────────────────────────────────────────────────────────────

check("session-replays dir", lambda: (
    (CLAUDE_DIR / "session-replays").exists(),
    f"{len(list((CLAUDE_DIR / 'session-replays').glob('*.md')))} replays" if
    (CLAUDE_DIR / "session-replays").exists() else "missing"
))

check("scripts present", lambda: (
    all((CLAUDE_DIR / "scripts" / s).exists() for s in [
        "voice-menubar.py","session-contract.py","discernment-scorer.py",
        "session-replay.py","standup.py","summarize.py","weekly.py","search_sessions.py",
        "knowledge.py","knowledge_indexer.py","db.py","embed.py",
        "project_mental_model.py","init_project_context.py","pre_commit_gate.py",
        "dashboard.py","index_session.py","smart-compact.py",
    ]),
    "all present"
))

check("py: sentence_transformers", lambda: check_py_pkg("sentence_transformers"))

def _db_count(db_path: Path, table: str) -> tuple:
    if not db_path.exists():
        return False, f"{db_path.name} not found"
    import sqlite3
    try:
        n = sqlite3.connect(str(db_path)).execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return True, f"{n} rows"
    except Exception as e:
        return False, str(e)

check("knowledge.db",   lambda: _db_count(CLAUDE_DIR / "knowledge.db", "knowledge"))
check("sessions.db",    lambda: _db_count(CLAUDE_DIR / "sessions.db", "sessions"))

check("discernment log", lambda: (
    (CLAUDE_DIR / "discernment-log.jsonl").exists(),
    f"{len((CLAUDE_DIR / 'discernment-log.jsonl').read_text().splitlines())} entries"
    if (CLAUDE_DIR / "discernment-log.jsonl").exists() else "missing — will be created on first session"
))

check("session-contracts dir", lambda: (
    (CLAUDE_DIR / "session-contracts").exists(),
    f"{len(list((CLAUDE_DIR / 'session-contracts').glob('*.json')))} contracts"
    if (CLAUDE_DIR / "session-contracts").exists() else "missing"
))

check("algorithmic-art skill", lambda: (
    (CLAUDE_DIR / "skills" / "algorithmic-art" / "image-to-art.html").exists(),
    "image-to-art.html present"
))

# ── Print results ─────────────────────────────────────────────────────────────

print("\n## Kit Health Check\n")
col = max(len(label) for _,label,_ in results) + 2
for icon, label, note in results:
    print(f"  {icon}  {label:<{col}} {note}")

print()
if failed == 0:
    print("All checks passed. Kit is healthy.")
else:
    print(f"{failed} check(s) failed. See above for details.")

sys.exit(0 if failed == 0 else 1)
