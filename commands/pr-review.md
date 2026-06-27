# PR Review

**PR**: $ARGUMENTS

> **Goal**: Surface real problems only — correctness bugs, security holes, data loss risks, and design flaws.
> Skip nitpicks (formatting, naming preferences, style opinions) unless they cause actual confusion or bugs.
> Every finding must include a confidence level. Drop anything below 70% confidence unless it's a security or data-loss risk.

---

## Step 1: Load Context

Before reviewing, understand what this PR is doing and why.

```bash
# Get PR metadata and description
gh pr view $ARGUMENTS

# See the full diff
gh pr diff $ARGUMENTS

# Understand what files changed and how much
gh pr diff $ARGUMENTS --stat
```

Read the PR description, linked issues, and any inline comments. If no PR number is given, use `git diff main...HEAD` and `git log main...HEAD --oneline`.

---

## Step 2: Correctness Review

**What to look for** (high-confidence bugs only):

- **Logic errors**: Off-by-one, wrong operator, inverted condition, incorrect null check
- **Race conditions / concurrency**: Shared mutable state accessed without synchronization; missing locks or atomic ops
- **Data integrity**: Missing transactions where multiple writes must be atomic; partial failure leaves data inconsistent
- **Resource leaks**: Connections, file handles, goroutines, timers opened but not closed on error paths
- **Breaking changes**: Public API, DB schema, message format, or config structure changed without migration or versioning
- **Incorrect error handling**: Errors silently swallowed, wrong error type returned, panic instead of graceful failure
- **Boundary conditions**: Empty input, zero values, max values, nil/null dereference

**Confidence threshold**: Only report if you are ≥80% confident it is an actual bug. If you're unsure, say so explicitly with your reasoning.

---

## Step 3: Security Review

**What to look for**:

- **Injection**: SQL, command, template, LDAP — any user-controlled input reaching an execution context without proper parameterization
- **Authentication / Authorization gaps**: Missing auth check on a new endpoint; privilege escalation path; JWT/token not validated
- **Sensitive data exposure**: Secrets, PII, tokens in logs, error messages, or API responses
- **Insecure deserialization**: Untrusted data deserialized without validation
- **Dependency risks**: New dependencies with known CVEs or from untrusted sources
- **Cryptographic misuse**: Weak algorithms (MD5/SHA1 for integrity), hardcoded keys, insufficient entropy

**Confidence threshold**: Report at ≥70% for security issues. For high-severity (RCE, auth bypass, data leak), report even at 60% — flag it as uncertain but worth investigating.

---

## Step 4: Design & Architecture Review

Only raise design concerns that will cause real pain — not theoretical future-proofing.

- **Wrong abstraction**: A function/module is doing two unrelated things that will diverge
- **Coupling**: A change in module A now requires changes in B, C, D — is this intended?
- **Missing contract**: A public interface or API has no clear invariants, making it easy to misuse
- **Scalability ceiling**: An approach that works at current scale but has an obvious O(n²) or similar hard limit that will be hit soon
- **Data model mistake**: A schema decision that will be painful to migrate (e.g., storing JSON blobs instead of proper columns, wrong index)

**Skip**: Stylistic architecture opinions, premature abstraction concerns, "I would have done it differently."

---

## Step 5: Test Quality Review

Only flag test issues that mean real bugs can ship undetected.

- **Missing test for the core behavior**: The PR adds/changes behavior with no corresponding test
- **Tests that don't test anything**: Assertions on implementation details (mocked internals), trivial smoke tests, `assert True`
- **Missing edge case tests**: The PR clearly handles an edge case in code but has no test for it
- **Test/code mismatch**: The test description says one thing but tests another

**Skip**: Low coverage percentage complaints without specific missing scenarios, preference for one test style over another.

---

## Step 6: Observability & Operability

Flag only if the change introduces a meaningful operational blind spot:

- **Silent failures in production paths**: Error or failure with no log, metric, or alert
- **Missing structured logging** for a new critical operation (auth, payments, data mutation)
- **No way to diagnose** if this feature starts misbehaving in prod
- **Feature flag / rollback gap**: High-risk change with no kill switch and no rollback plan

---

## Step 7: Present Review for Approval

Compile all findings into the review body below and **show it to the user**. Do NOT post to GitHub yet.

```
## PR Review

### Summary
[1-2 sentence overall assessment: what this PR does, and the most important finding]

---

### 🔴 Must Fix (Merge Blocker)
<!-- Correctness bugs, security issues, data loss risks — HIGH confidence -->

- **[Category]** `file:line` — Description of what's wrong and why it matters.
  > Confidence: X% | Fix: [specific suggestion]

---

### 🟡 Should Fix (Strong Recommendation)
<!-- Design flaws, error handling gaps, missing tests for critical paths — HIGH confidence -->

- **[Category]** `file:line` — Description.
  > Confidence: X% | Fix: [specific suggestion]

---

### 🔵 Consider (Low Priority)
<!-- Non-critical improvements with high confidence — keep this section SHORT, max 3 items -->

- **[Category]** `file:line` — Description.
  > Confidence: X%

---

### ✅ Strengths
<!-- What's notably good — always include at least one -->

- [What the PR does well]

---

### Verdict
**[ APPROVE | REQUEST CHANGES | COMMENT ]** — [One sentence rationale]
```

After presenting, ask: **"Does this look good to post, or would you like to adjust anything?"**

Wait for explicit confirmation before proceeding to Step 8.

---

## Step 8: Post to GitHub (After Approval)

Once the user approves the review content, post it as a single GitHub review:

```bash
# For REQUEST CHANGES verdict:
gh pr review $ARGUMENTS --request-changes --body "<approved review body>"

# For APPROVE verdict:
gh pr review $ARGUMENTS --approve --body "<approved review body>"

# For COMMENT only verdict:
gh pr review $ARGUMENTS --comment --body "<approved review body>"
```

**Verdict rules**:
- `REQUEST CHANGES`: Any 🔴 Must Fix item exists
- `APPROVE with notes`: Only 🟡 or 🔵 items, nothing blocking
- `COMMENT`: Informational only, no action required

---

## Confidence Scoring Guide

Use this when deciding what to include:

| Confidence | Meaning | Include? |
|---|---|---|
| 90–100% | Certain bug/issue | Always |
| 80–89% | Very likely an issue | Yes |
| 70–79% | Probably an issue | Yes, note uncertainty |
| 60–69% | Possible issue | Security/data-loss only |
| <60% | Speculation | No — skip it |

**Signal-to-noise rule**: If you have 10+ findings, you're probably including low-confidence nitpicks. Prune to the 5–7 that matter most. A review with 3 real findings is better than one with 15 marginal ones.

---

## What to Skip

Explicitly do NOT flag:

- Formatting, whitespace, indentation (unless it causes actual parsing bugs)
- Variable/function naming preferences
- "I'd have organized this differently" without a concrete harm
- Missing comments or docs (unless the code is genuinely unreadable)
- Performance micro-optimizations without evidence of a bottleneck
- Architecture opinions that don't affect the current use case
- Test coverage % below some threshold if critical paths are covered
