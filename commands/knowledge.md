---
allowed-tools: Bash
argument-hint: add <fact> | query <terms> | list [--n N] | stats | delete <id>
description: Manage the personal knowledge base — add facts, query, list, stats
model: haiku
---

Parse `$ARGUMENTS` and route to the knowledge CLI.

If `$ARGUMENTS` is empty or `--help`, print the help text below without running the script.

Otherwise run:
```bash
python3 ~/.claude/scripts/knowledge.py $ARGUMENTS
```

Display the output cleanly as-is.

---

**Available subcommands:**

| Subcommand | What it does |
|---|---|
| `add <fact> [--source <url>]` | Store a fact manually |
| `query <terms>` | Search by keywords or semantics |
| `list [--n N]` | Show last N facts (default 10) |
| `stats` | Total count, breakdown by type, date range |
| `delete <id>` | Remove a fact by its ID |

**Examples:**

```bash
# Add a fact manually
python3 ~/.claude/scripts/knowledge.py add "Claude Code hooks fire in order: PreToolUse, PostToolUse, UserPromptSubmit, Stop"

# Query the knowledge base
python3 ~/.claude/scripts/knowledge.py query "hooks"

# List recent entries
python3 ~/.claude/scripts/knowledge.py list --n 15

# Show stats
python3 ~/.claude/scripts/knowledge.py stats

# Delete entry by ID
python3 ~/.claude/scripts/knowledge.py delete 42
```
