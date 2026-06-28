#!/usr/bin/env python3
"""
Knowledge RAG — store and query extracted facts in ~/.claude/knowledge.db.

store(facts, source_url, source_type, session_id):
    Embed each fact and upsert into knowledge.db.

query(prompt, top_n=5):
    FTS5 keyword search → vector similarity fallback.
    Returns list of matching facts with source.

extract_facts(text, source_url):
    Uses Haiku to pull 5-10 discrete facts from raw text.
"""
import json, os, sys, boto3
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from db import knowledge_db, vec_to_json, cosine_distance
from embed import embed

SIMILARITY_THRESHOLD = 0.35
TOP_N = 5

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID   = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)

EXTRACT_PROMPT = """\
Extract 5-10 discrete, self-contained facts from the content below.
Each fact must be independently useful — no "see above" references.
Return ONLY a JSON array of strings. No prose, no markdown.

Source: {url}

Content:
{content}

Example output:
["AgentFS uses copy-on-write overlay so agents can't corrupt real files",
 "AgentFS free tier includes 3 GB sync/month",
 "agentfs diff <session> shows what the agent changed"]"""


def extract_facts(text: str, source_url: str) -> list:
    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "messages": [{"role": "user", "content": EXTRACT_PROMPT.format(
                url=source_url or "unknown",
                content=text[:6000],
            )}],
        }
        resp = client.invoke_model(
            modelId=MODEL_ID, body=json.dumps(body),
            contentType="application/json", accept="application/json",
        )
        raw = json.loads(resp["body"].read())["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rsplit("```", 1)[0].strip()
        facts = json.loads(raw)
        return [f for f in facts if isinstance(f, str) and len(f) > 10]
    except Exception:
        return []


def store(facts: list, source_url: str = "", source_type: str = "web",
          session_id: str = "") -> int:
    if not facts:
        return 0
    conn = knowledge_db()
    stored = 0
    for fact in facts:
        # Skip near-duplicates — check FTS first
        # Use first 5 words as phrase match to detect near-duplicates
        words = fact.split()[:5]
        phrase = " ".join(words)
        try:
            existing = conn.execute(
                "SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT 1",
                (f'"{phrase}"',),
            ).fetchone()
            if existing:
                continue
        except Exception:
            pass
        vec = vec_to_json(embed(fact))
        conn.execute(
            "INSERT INTO knowledge (source_url, source_type, fact, embedding, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_url, source_type, fact, vec, session_id),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO knowledge_fts (rowid, source_url, source_type, fact) VALUES (?, ?, ?, ?)",
            (row_id, source_url or "", source_type, fact),
        )
        stored += 1
    conn.commit()
    return stored


def query(prompt: str, top_n: int = TOP_N) -> list:
    conn = knowledge_db()

    # FTS keyword search first — use individual words as OR terms
    try:
        words = [w for w in prompt.split() if len(w) > 3][:6]
        if words:
            fts_query = " OR ".join(words)
            rows = conn.execute(
                """SELECT k.fact, k.source_url, k.source_type, k.added_at
                   FROM knowledge_fts
                   JOIN knowledge k ON knowledge_fts.rowid = k.id
                   WHERE knowledge_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (fts_query, top_n),
            ).fetchall()
            if rows:
                return [{"fact": r["fact"], "source": r["source_url"],
                         "type": r["source_type"], "match": "keyword"} for r in rows]
    except Exception:
        pass

    # Vector fallback
    vec = embed(prompt[:500])
    rows = conn.execute(
        "SELECT fact, source_url, source_type, embedding FROM knowledge WHERE embedding IS NOT NULL"
    ).fetchall()
    scored = []
    for row in rows:
        dist = cosine_distance(vec, row["embedding"])
        if dist <= SIMILARITY_THRESHOLD:
            scored.append((dist, row["fact"], row["source_url"], row["source_type"]))
    scored.sort(key=lambda x: x[0])
    return [{"fact": f, "source": u, "type": t, "match": "semantic"}
            for _, f, u, t in scored[:top_n]]
