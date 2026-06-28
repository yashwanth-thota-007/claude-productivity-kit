---
allowed-tools: Read, Write, Edit, Bash
argument-hint: [feature-name]
description: Scaffold and implement a new feature end-to-end with tests and review
model: sonnet
---

# Create Feature: $ARGUMENTS

## Step 1: Orient

```bash
git branch --show-current
git status
```

Read `<project-root>/.claude/prime-results.md` if it exists. Scan `.claude/docs/` for architecture context. Understand the existing patterns before writing a line.

## Step 2: Plan (surface before implementing)

State explicitly:
- What this feature does and what it does NOT do
- Which files will be created or modified
- What the data flow / API contract looks like
- Any non-obvious tradeoffs or constraints

Ask the user to confirm the plan if it involves schema changes, new dependencies, or public API changes.

## Step 3: Branch + Implement

```bash
git checkout -b feature/$ARGUMENTS
```

Implement the minimum code that satisfies the requirements. Follow existing patterns exactly — match naming, file structure, error handling style. No extra abstractions, no future-proofing.

## Step 4: Quality Gate

Run `/code-complete $ARGUMENTS`:
- Tests are written and pass
- Code reviewer finds no 🔴 blockers
- Fix loop resolves any 🟡 issues

Do not proceed to Step 5 until the gate is clean.

## Step 5: Docs

Update only what is directly affected:
- Inline comments only for non-obvious logic
- Update `prime-results.md` or `.claude/docs/` if a new pattern or constraint was established
- Update API docs if a new endpoint or contract was added

## Step 6: Ship

```bash
git add <specific files>
git diff --staged
```

Confirm with the user, then commit. Offer to run `/auto-pr`.
