#!/usr/bin/env python3
"""
Stop hook — scores the last Claude response using three discernment dimensions:
  Product:     accuracy, relevance, coherence, completeness of the output
  Process:     quality of reasoning, tool usage, step sequencing, attention gaps
  Performance: communication style, conciseness, appropriate tone, transparency

If the composite score is below RETRY_THRESHOLD, outputs a decision:block asking
Claude to retry with specific improvement guidance. Otherwise exits silently.

Calls Bedrock (Haiku) to keep cost low. Reads last assistant turn from the
current session transcript.
"""
import json, os, sys, pathlib, boto3
from typing import Optional

# --- Config ---
RETRY_THRESHOLD       = 6.5   # out of 10 — below this triggers a retry nudge
MISCALIBRATION_FLOOR  = 4.0   # below this, scorer is likely wrong — skip retry
SESSION_BAIL_N        = 3     # sub-threshold scores in a session → compute session offset
SESSION_DIR           = pathlib.Path.home() / ".claude" / "projects"
CONTRACTS_DIR         = pathlib.Path.home() / ".claude" / "session-contracts"
MODEL_ID              = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
)
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

SCORE_PROMPT = """\
You are an AI quality evaluator. Score the LAST assistant response across three dimensions.
Be critical but fair. Return ONLY valid JSON — no prose, no markdown.

{tool_context}\
{contract_context}\
=== RECENT CONVERSATION CONTEXT (last {n_turns} turns) ===
{conversation_context}
=== END CONTEXT ===

=== LAST ASSISTANT RESPONSE (the one to score) ===
{response}
=== END ===

IMPORTANT: The response must be evaluated in light of the conversation context above.
Do NOT penalise the response for omitting information already established earlier in the
conversation — brevity that relies on prior context is a feature, not a flaw.
Where a session contract is provided, score each dimension against the stated goals —
e.g. if the contract says "concise" and the response is verbose, penalise Performance;
if the product goal is misaddressed, penalise Product.

Score each dimension 1–10 and give a one-line reason:

{{
  "product": {{
    "score": <int 1-10>,
    "reason": "<accuracy, relevance, completeness — note if it missed the contract product goal>"
  }},
  "process": {{
    "score": <int 1-10>,
    "reason": "<quality of reasoning, tool use, step sequencing — note contract process alignment>"
  }},
  "performance": {{
    "score": <int 1-10>,
    "reason": "<tone, conciseness, transparency — note contract performance/effort alignment>"
  }},
  "composite": <float, weighted average: product 40% + process 35% + performance 25%>,
  "retry_guidance": "<if composite < {threshold}, one specific instruction to improve the response; else empty string>"
}}"""


def load_session_contract(session_id: str) -> Optional[dict]:
    p = CONTRACTS_DIR / f"{session_id}.json"
    if not p.exists():
        return None
    try:
        c = json.loads(p.read_text())
        if c.get("_skipped"):
            return None
        return c
    except Exception:
        return None


def format_contract_context(c: dict) -> str:
    lines = [
        "=== SESSION CONTRACT (score against these goals) ===",
        f"Title      : {c.get('session_title', '?')}",
        f"Product    : {c.get('product', 'unspecified')}",
        f"Process    : {c.get('process', 'unspecified')}",
        f"Performance: {c.get('performance', 'unspecified')}",
        f"Effort     : {c.get('effort', 'normal')}",
        "=== END CONTRACT ===\n",
    ]
    return "\n".join(lines)


def get_session_entries(session_id: str) -> list:
    """Return all transcript entries for the given session."""
    for project_dir in SESSION_DIR.iterdir():
        transcript = project_dir / f"{session_id}.jsonl"
        if not transcript.exists():
            continue
        entries = []
        for line in transcript.read_text().strip().splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries
    return []


CONTEXT_TURNS = 6  # number of recent user+assistant turns to include as context


def get_conversation_context(entries: list, skip_last_assistant: bool = True) -> str:
    """
    Extract the last CONTEXT_TURNS user/assistant text exchanges as a readable
    thread, excluding the final assistant turn (which is the one being scored).
    """
    turns = []
    skipped_last = False
    for entry in reversed(entries):
        role = entry.get("type")
        if role == "assistant":
            if not skipped_last and skip_last_assistant:
                skipped_last = True
                continue
            content = entry.get("message", {}).get("content", [])
            text = " ".join(
                b["text"] for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
            if text:
                turns.append(f"Assistant: {text[:400]}")
        elif role == "user":
            msg = entry.get("message", {})
            if isinstance(msg, dict):
                text = " ".join(
                    b["text"] for b in msg.get("content", [])
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
            else:
                text = str(msg).strip()
            if text and not text.startswith("<"):  # skip system injections
                turns.append(f"User: {text[:300]}")
        if len(turns) >= CONTEXT_TURNS * 2:
            break
    turns.reverse()
    return "\n".join(turns) if turns else "(no prior context)"


def get_last_assistant_response(entries: list) -> Optional[str]:
    """Read the most recent assistant text turn from transcript entries."""
    for entry in reversed(entries):
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content", [])
        text_parts = [
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if text_parts:
            return "\n".join(text_parts)
    return None


def get_tool_outputs(entries: list) -> list[str]:
    """Collect stdout from bash results + file paths from Write/Edit calls."""
    outputs = []
    for entry in entries:
        # Bash tool results
        if entry.get("type") == "tool_result":
            content = entry.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        text = block.get("content", "")
                        if text and len(text) > 10:
                            outputs.append(text[:300])
            elif isinstance(content, str) and len(content) > 10:
                outputs.append(content[:300])
        # Write/Edit tool calls — treat file_path as a verified artifact
        if entry.get("type") == "assistant":
            for block in entry.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if block.get("name") in ("Write", "Edit", "MultiEdit"):
                        path = block.get("input", {}).get("file_path", "")
                        if path:
                            outputs.append(path)
    return outputs[-10:]


def has_verified_tool_output(response_text: str, tool_outputs: list[str]) -> bool:
    """
    Return True if the response references content that appeared verbatim
    in tool call results — i.e. the response is reporting real output, not
    generating claims from scratch.
    """
    if not tool_outputs:
        return False
    response_lower = response_text.lower()
    for output in tool_outputs:
        # Check if a meaningful chunk of the tool output appears in the response
        lines = [l.strip() for l in output.splitlines() if len(l.strip()) > 15]
        for line in lines[:5]:
            if line.lower() in response_lower:
                return True
    return False


def build_tool_context(tool_outputs: list[str], has_verified: bool) -> str:
    """Build an optional preamble for the scoring prompt when tool output is present."""
    if not has_verified:
        return ""
    snippets = "\n".join(f"  {o[:150]}" for o in tool_outputs[:3])
    return (
        "IMPORTANT CONTEXT: The assistant response below references output from "
        "real shell commands executed in this session. The following tool outputs "
        "were confirmed by the system (not generated by the assistant). Do NOT "
        "penalise the response for describing these verified outputs:\n"
        f"{snippets}\n\n"
    )


def score_response(text: str, tool_context: str, conv_context: str, contract_context: str) -> dict:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    prompt = SCORE_PROMPT.format(
        response=text[:4000],
        threshold=RETRY_THRESHOLD,
        tool_context=tool_context,
        contract_context=contract_context,
        conversation_context=conv_context[:2000],
        n_turns=CONTEXT_TURNS,
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    raw = json.loads(resp["body"].read())
    text_out = raw["content"][0]["text"].strip()
    if text_out.startswith("```"):
        text_out = "\n".join(text_out.splitlines()[1:])
        text_out = text_out.rsplit("```", 1)[0].strip()
    return json.loads(text_out)


def get_session_scores(session_id: str, log_path: pathlib.Path) -> list:
    """Return all composite scores logged for this session so far."""
    if not log_path.exists():
        return []
    scores = []
    for line in log_path.read_text().splitlines():
        try:
            entry = json.loads(line)
            if entry.get("session_id") == session_id:
                scores.append(float(entry["composite"]))
        except Exception:
            continue
    return scores


def compute_session_offset(session_scores: list) -> float:
    """
    Average of all session scores so far. Used as the effective threshold
    once SESSION_BAIL_N low scores have accumulated — the scorer is calibrated
    to this session's typical score level rather than the global threshold.
    """
    return sum(session_scores) / len(session_scores)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    if not session_id:
        sys.exit(0)

    entries = get_session_entries(session_id)
    response_text = get_last_assistant_response(entries)
    if not response_text or len(response_text) < 80:
        sys.exit(0)

    tool_outputs  = get_tool_outputs(entries)
    has_verified  = has_verified_tool_output(response_text, tool_outputs)
    tool_context  = build_tool_context(tool_outputs, has_verified)
    conv_context  = get_conversation_context(entries)
    contract      = load_session_contract(session_id)
    contract_ctx  = format_contract_context(contract) if contract else ""

    try:
        scores = score_response(response_text, tool_context, conv_context, contract_ctx)
    except Exception:
        sys.exit(0)

    composite = float(scores.get("composite", 10))

    log_path = pathlib.Path.home() / ".claude" / "discernment-log.jsonl"

    # Check how many sub-threshold scores this session has already accumulated
    prior_scores     = get_session_scores(session_id, log_path)
    prior_low_count  = sum(1 for s in prior_scores if s < RETRY_THRESHOLD)
    session_bailed   = prior_low_count >= SESSION_BAIL_N

    # Compute session offset: average of all prior scores for this session
    # Once bailed, use this as the effective threshold instead of the global one
    session_offset   = compute_session_offset(prior_scores) if prior_scores else None
    effective_threshold = session_offset if session_bailed and session_offset else RETRY_THRESHOLD

    with open(log_path, "a") as f:
        f.write(json.dumps({
            "session_id": session_id,
            "composite": composite,
            "product": scores.get("product"),
            "process": scores.get("process"),
            "performance": scores.get("performance"),
            "had_verified_tool_output": has_verified,
            "had_contract": contract is not None,
            "session_bailed": session_bailed,
            "session_offset": round(session_offset, 2) if session_offset else None,
            "skipped_retry_floor": composite < MISCALIBRATION_FLOOR,
        }) + "\n")

    # Miscalibration floor — score this low almost certainly means the scorer
    # is wrong (e.g. flagging real CLI output as hallucination), not the response
    if composite < MISCALIBRATION_FLOOR:
        sys.exit(0)

    if composite < effective_threshold:
        guidance   = scores.get("retry_guidance", "")
        product_r  = scores["product"]["reason"]
        process_r  = scores["process"]["reason"]
        perf_r     = scores["performance"]["reason"]

        threshold_note = (
            f"session offset {effective_threshold:.1f}" if session_bailed
            else f"threshold {RETRY_THRESHOLD}"
        )
        message = (
            f"[Discernment Score: {composite:.1f}/10 — below {threshold_note}]\n\n"
            f"Product ({scores['product']['score']}/10): {product_r}\n"
            f"Process ({scores['process']['score']}/10): {process_r}\n"
            f"Performance ({scores['performance']['score']}/10): {perf_r}\n\n"
            f"Improvement needed: {guidance}\n\n"
            f"Please revise your response addressing the above."
        )
        print(json.dumps({"decision": "block", "reason": message}))


if __name__ == "__main__":
    main()
