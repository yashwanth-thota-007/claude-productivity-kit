---
allowed-tools: Read, Write, Edit, Bash, Grep
argument-hint: [branch-name or PR title hint]
description: One-shot ship flow — code-complete gate, commit, push, PR. From done to merged in one command.
model: sonnet
---

# /quick-ship — One-Shot Ship Flow

Arguments: **$ARGUMENTS**

Run the full ship pipeline without stopping for confirmations at each step. The gate is /code-complete; if it passes, everything else is automated.

## Step 1: Pre-flight check

```bash
git status --short
git log --oneline -3
git rev-parse --abbrev-ref HEAD
```

If there are no changes at all, stop and tell the user there's nothing to ship.

## Step 2: Run the code-complete gate

Run `/code-complete $ARGUMENTS` inline.

- If it returns NEEDS WORK with 🔴 Must Fix items: **stop**. List the issues and tell the user to fix them before shipping.
- If it returns CLEAN or only 🟡/🔵 items: proceed.

## Step 3: Stage and commit

```bash
git add -p  # review changes interactively? No — just:
git diff --staged --stat
git diff --stat HEAD
```

Stage all changes:
```bash
git add -A
git diff --staged --stat
```

Generate commit message from the work done:
- Use conventional commit format: `type(scope): description`
- Types: feat, fix, refactor, docs, test, chore
- Keep under 72 chars
- Include a short body if the change needs explanation

Commit:
```bash
git commit -m "<generated message>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

## Step 4: Push

```bash
git push -u origin HEAD
```

## Step 5: Generate PR

```bash
python3 ~/.claude/scripts/auto-pr.py "$PWD"
```

Use the title and body from the output. Create the PR:

```bash
gh pr create --title "<title>" --body "<body>"
```

If the user passed arguments to /quick-ship, use them as a hint to refine the PR title.

## Step 6: Report

Print a clean summary:

```
✅ Shipped

Commit  : <hash> — <message>
Branch  : <branch>
PR      : <url>

What's in it:
<2-3 bullets from PR body ##Changes section>
```

## Error handling

- If `gh` CLI is not authenticated: tell the user to run `gh auth login` and re-run
- If push is rejected (branch protection): explain and suggest opening a draft PR manually
- If /code-complete gate fails with 🔴 items: list them clearly, tell user to fix and re-run /quick-ship
