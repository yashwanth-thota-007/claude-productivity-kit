---
allowed-tools: Read, Write, Edit, Bash, Grep
argument-hint: [file-or-feature-name]
description: Quality gate for finished coding tasks — tests, review, fix loop, checkpoint
model: sonnet
---

# Code Complete — Quality Gate

Run the full quality pipeline on a finished coding task: **$ARGUMENTS**

## Step 1: Establish Scope

```bash
# What changed
git diff --stat HEAD
git diff --name-only HEAD
```

If `$ARGUMENTS` specifies a file or feature, focus on that. Otherwise use all files in the current diff.

## Step 2: Write Tests

Spawn the `write-tests` agent on every changed file that lacks test coverage:

```
For each changed file without a corresponding test file:
  - Identify testable functions, edge cases, error paths
  - Write unit tests (and integration tests if the file touches external systems)
  - Tests must assert concrete behavior — no smoke tests, no empty bodies
  - Run tests immediately and fix failures before proceeding
```

**Gate**: All written tests must pass before Step 3.

## Step 3: Code Review

Spawn the `code-reviewer` agent on the full diff. It must use confidence-scored output:

```
Review the staged/committed diff for:
  🔴 Must Fix  — correctness bugs, security holes, data loss (≥80% confidence)
  🟡 Should Fix — error handling gaps, missing test coverage for critical paths (≥75%)
  🔵 Consider  — low-priority improvements (≥85% confidence, max 3)

Skip: formatting preferences, naming opinions, speculative future concerns.
Every finding must include: file:line, confidence %, specific fix suggestion.
```

**Gate**: No 🔴 Must Fix items before Step 4.

## Step 4: Fix Loop

If Step 3 surfaces 🔴 or 🟡 items:
1. Fix each issue in priority order
2. Re-run affected tests
3. Re-run the code-reviewer agent on only the fixed sections
4. Repeat until no 🔴 items remain

Maximum 3 fix iterations. If 🔴 items persist after 3 loops, surface them to the user and stop.

## Step 5: Checkpoint

Once all gates pass:

```bash
git diff --staged --stat
```

Summarize what was implemented, what tests were written, what issues were found and fixed.

Output a commit-ready summary in this format:

```
✅ Code Complete: [feature/file name]

Implemented: [what was built — 1 sentence]
Tests added: [N unit / N integration tests — key scenarios covered]
Issues fixed: [what the reviewer caught, or "none"]
Ready to commit: yes
```

Ask the user: "Looks good to commit? Want me to run /auto-pr after?"
