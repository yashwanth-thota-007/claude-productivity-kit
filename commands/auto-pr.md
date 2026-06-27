# Auto PR

Draft a GitHub pull request title and body from the latest session replay + git diff, then create it.

## Instructions

1. Run the generator script against the current working directory:

```bash
python3 ~/.claude/scripts/auto-pr.py "$PWD"
```

2. Parse the JSON output — it has `title` and `body` keys.

3. Show the user the drafted title and body. Ask: "Does this look good? Want to adjust anything before I create the PR?"

4. Once confirmed, create the PR using gh CLI:

```bash
gh pr create --title "<title>" --body "<body>" --draft
```

Use `--draft` by default. If the user says it's ready for review, omit `--draft`.

5. Return the PR URL.

## Notes

- If the script errors (no replay, no diff), tell the user what's missing and suggest they either run a session first or be in a git repo with changes.
- Don't invent changes — use only what the script returns.
- If the user is not in a git repo, the script will still run but diff will be empty; the PR body will be based on the session replay alone.
