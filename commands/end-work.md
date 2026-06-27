# /end-work — Clean up worktree session

When invoked:

## 1. Verify we're in a worktree

Check if we're on a `claude/*` branch: `git rev-parse --abbrev-ref HEAD`
If not, tell the user there's nothing to end.

## 2. Check for uncommitted changes

Run `git status --short`. If dirty:
- Ask: *"You have uncommitted changes. Commit them, stash, or discard before ending?"*
- Wait for user decision before proceeding.

## 3. Check for unpushed commits

Run `git log origin/HEAD..HEAD --oneline 2>/dev/null`. If commits exist:
- Ask: *"You have unpushed commits. Push and open a PR, or just keep the branch?"*

## 4. Optional: push + PR

If user wants a PR, run:
```bash
git push -u origin <branch>
gh pr create --fill
```

## 5. Exit the worktree

Use `ExitWorktree(action: "keep")` — always keep the branch so work isn't lost.

## 6. Unregister the session

```bash
python3 ~/.claude/scripts/session-manager.py unregister --worktree <worktree_path>
```

## 7. Confirm

```
✓ Session ended
  Branch kept: claude/<slug>
  PR: <url or "not opened">
  Active sessions remaining: <N>
```
