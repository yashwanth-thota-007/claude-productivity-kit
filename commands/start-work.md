# /start-work — Smart Worktree Session Starter

When invoked, follow this exact flow:

## 1. Read context

- Check if currently inside a git repo: `git rev-parse --show-toplevel`
- Get current branch: `git rev-parse --abbrev-ref HEAD`
- List active sessions on this repo: `python3 ~/.claude/scripts/session-manager.py list --repo <repo_root>`

## 2. Assess if a worktree is needed

Ask yourself:
- Is this read-only / exploratory work (questions, debugging, code review)? → **Skip worktree, just say so.**
- Is this a real task (implement, add, fix, refactor, build, migrate, etc.)? → **Create worktree.**
- Is the user already in a worktree branch (`claude/*`)? → **Already isolated, say so and stop.**

If the intent is ambiguous, ask the user: *"Is this exploratory or are you starting development work?"*

## 3. Determine branch name

- If the user passed a name (e.g., `/start-work auth-refactor`), use it as-is.
- Otherwise, infer from context: current task description, recent message, or ask.
- Branch format: `claude/<slug>` (e.g., `claude/auth-refactor`, `claude/fix-payment-timeout`)
- Keep slugs short, lowercase, hyphenated.

## 4. Check for conflicts

Look at active sessions from the registry. If another session is already on the same branch name, suggest an alternative (append `-2` or a timestamp suffix).

## 5. Create the worktree

Use the `EnterWorktree` tool with the branch name (without the `claude/` prefix — the tool handles naming):

```
EnterWorktree(name: "<slug>")
```

This creates `.claude/worktrees/<slug>` and a branch `claude/<slug>`, then switches the session into it.

## 6. Register the session

After the worktree is created, register it:

```bash
python3 ~/.claude/scripts/session-manager.py register \
  --repo <repo_root> \
  --branch claude/<slug> \
  --worktree <worktree_path> \
  --task "<task description>"
```

## 7. Confirm to user

Print a clear summary:
```
✓ Worktree created
  Branch:   claude/<slug>
  Path:     <worktree_path>
  Task:     <task>
  Sessions: <N> active on this repo

You're now isolated. Other sessions on this repo won't conflict.
Run /end-work when done to clean up and open a PR.
```

## 8. Prime the new context

Run `/prime` to load project context into the new worktree session.

---

## Skip conditions (do not create worktree if):
- Already in a `claude/*` branch
- Not in a git repo
- User explicitly says "no worktree" or "just exploring"
- Task is clearly read-only (explain, review, search, list, show, what, why, how)
