---
allowed-tools: Read, Bash
argument-hint: <url> | <text> | --query <question>
description: Store knowledge from a URL or text into the local RAG knowledge base, or query it
model: sonnet
---

# Remember

Store or query knowledge in `~/.claude/knowledge.db`: **$ARGUMENTS**

## If $ARGUMENTS starts with http

Fetch the URL and extract facts:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/scripts')
from knowledge import extract_facts, store

# Fetch content
import urllib.request
try:
    with urllib.request.urlopen('$ARGUMENTS', timeout=15) as r:
        content = r.read().decode('utf-8', errors='ignore')
except Exception as e:
    print(f'Fetch failed: {e}')
    sys.exit(1)

facts = extract_facts(content, '$ARGUMENTS')
n = store(facts, source_url='$ARGUMENTS', source_type='manual')
print(f'Stored {n} fact(s) from $ARGUMENTS')
for f in facts:
    print(f'  • {f}')
"
```

## If $ARGUMENTS starts with --query

Search the knowledge base:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/scripts')
from knowledge import query
results = query('$(echo $ARGUMENTS | sed s/--query//)')
if not results:
    print('No matching knowledge found.')
else:
    for r in results:
        print(f\"[{r['type']}] {r['fact']}\")
        if r['source']:
            print(f\"  source: {r['source']}\")
"
```

## If $ARGUMENTS is plain text

Store it directly as a single fact:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/scripts')
from knowledge import store
n = store(['$ARGUMENTS'], source_url='', source_type='manual')
print(f'Stored fact: $ARGUMENTS')
"
```

## Show recent knowledge

If no arguments given, show the 10 most recently added facts:

```bash
python3 -c "
import sys, sqlite3; sys.path.insert(0, '$HOME/.claude/scripts')
from db import knowledge_db
conn = knowledge_db()
rows = conn.execute('SELECT fact, source_url, added_at FROM knowledge ORDER BY added_at DESC LIMIT 10').fetchall()
if not rows:
    print('Knowledge base is empty.')
else:
    for r in rows:
        print(f\"[{r['added_at'][:10]}] {r['fact']}\")
        if r['source_url']:
            print(f\"  {r['source_url']}\")
"
```
