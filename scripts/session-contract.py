#!/usr/bin/env python3
"""
UserPromptSubmit hook — session contract manager.

First message of a session:
  - Uses Haiku to extract Product / Process / Performance goals + effort level
  - Saves contract to ~/.claude/session-contracts/<session_id>.json
  - Injects it as additionalSystemPrompt so Claude is anchored to the goals

Every subsequent message:
  - Re-injects the contract as a lightweight reminder
  - Detects topic drift: if the new prompt looks like a new task that diverges
    from the original domain, injects a warning asking Claude to flag it inline
    and suggest starting a fresh session
"""
import json, os, sys, time, boto3
from pathlib import Path
from typing import Optional

CONTRACTS_DIR    = Path.home() / ".claude" / "session-contracts"
POMODORO_SIGNAL  = Path.home() / ".claude" / "pomodoro-signal.json"
MIN_CHARS        = 40

EFFORT_MINUTES = {"quick": 25, "normal": 50, "deep": 90}
AWS_REGION    = os.environ.get("AWS_REGION", "eu-central-1")
MODEL_ID      = os.environ.get(
    "ANTHROPIC_SMALL_FAST_MODEL",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)

# Prompts that are pure questions / conversational — skip contract extraction
SKIP_PATTERNS = ["what is", "what's", "how does", "can you", "do you",
                 "tell me about", "explain ", "why is", "when did", "who is"]

# Signals a new-task intent (as opposed to a follow-up in the current context)
TASK_KEYWORDS = ["implement", "add", "build", "fix", "refactor", "create",
                 "update", "migrate", "write", "set up", "integrate", "replace",
                 "remove", "help me", "i need", "i want", "make"]

EXTRACT_PROMPT = """\
Extract a session contract from this opening message.
Return ONLY valid JSON — no prose, no markdown fences.

Message: {prompt}

{{
  "product": "<what they want to create/achieve, ≤12 words>",
  "process": "<how they want it approached, or 'unspecified'>",
  "performance": "<desired tone/depth/behavior, or 'unspecified'>",
  "effort": "quick | normal | deep",
  "domain_keywords": ["3-8 core topic words lowercase"],
  "session_title": "<5-word title for this session>"
}}

effort rules: 'quick' if they signal speed/simplicity, 'deep' if they signal \
thoroughness/research/comprehensive, else 'normal'."""


def is_conversational(p: str) -> bool:
    return (p.endswith("?") or any(p.startswith(x) for x in SKIP_PATTERNS))


def is_task_intent(p: str) -> bool:
    return any(kw in p for kw in TASK_KEYWORDS)


def contract_path(session_id: str) -> Path:
    return CONTRACTS_DIR / f"{session_id}.json"


def load_contract(session_id: str) -> Optional[dict]:
    p = contract_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save_contract(session_id: str, contract: dict):
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    contract["session_id"] = session_id
    contract["ts"] = time.time()
    contract_path(session_id).write_text(json.dumps(contract, indent=2))


def extract_contract(prompt: str) -> Optional[dict]:
    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": EXTRACT_PROMPT.format(prompt=prompt[:800])}],
        }
        resp = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:]).rsplit("```", 1)[0].strip()
        return json.loads(raw)
    except Exception:
        return None


def drift_score(prompt_lower: str, keywords: list) -> float:
    """Fraction of domain keywords absent from the new prompt. 1.0 = total drift."""
    if not keywords:
        return 0.0
    absent = sum(1 for k in keywords if k not in prompt_lower)
    return absent / len(keywords)


def format_contract_context(c: dict) -> str:
    effort_map = {
        "quick": "Be efficient — avoid over-engineering, skip elaborate preamble.",
        "deep":  "Think thoroughly — explore edge cases, surface tradeoffs, don't rush.",
        "normal": "",
    }
    effort_note = effort_map.get(c.get("effort", "normal"), "")
    parts = [f"[SESSION CONTRACT — {c.get('session_title', 'this session')}]"]
    parts.append(f"Product goal : {c.get('product', 'unspecified')}")
    parts.append(f"Process style: {c.get('process', 'unspecified')}")
    parts.append(f"Performance  : {c.get('performance', 'unspecified')}")
    if effort_note:
        parts.append(f"Effort level : {c.get('effort')} — {effort_note}")
    parts.append("Stay aligned to these goals. If your response drifts from them, self-correct.")
    return "\n".join(parts)


def format_drift_warning(c: dict) -> str:
    return (
        f"[SESSION DRIFT DETECTED]\n"
        f"The current session contract is: \"{c.get('session_title', 'the original goal')}\" "
        f"(Product: {c.get('product', '?')}).\n\n"
        f"The user's latest message appears to be a significantly different topic.\n\n"
        f"Open your response by briefly acknowledging this shift. Offer two options:\n"
        f"1. Continue — address the new request in this session (note it may lose coherence)\n"
        f"2. Fresh start — recommend the user open a new session for the new topic\n\n"
        f"Keep this notice to 2-3 sentences. Then proceed with whichever makes more sense."
    )


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    prompt = hook_input.get("prompt", "").strip()

    if not session_id or len(prompt) < MIN_CHARS:
        sys.exit(0)

    existing = load_contract(session_id)

    # ── First message: extract and save contract ─────────────────────────────
    if existing is None:
        if is_conversational(prompt.lower()):
            # Mark with a sentinel so we don't retry on every turn
            save_contract(session_id, {
                "product": "unspecified", "process": "unspecified",
                "performance": "unspecified", "effort": "normal",
                "domain_keywords": [], "session_title": "general conversation",
                "_skipped": True,
            })
            sys.exit(0)

        contract = extract_contract(prompt)
        if not contract:
            sys.exit(0)

        save_contract(session_id, contract)

        # Signal the menu bar app to auto-start a Pomodoro timer
        effort  = contract.get("effort", "normal")
        minutes = EFFORT_MINUTES.get(effort, 50)
        POMODORO_SIGNAL.write_text(json.dumps({
            "session_id": session_id,
            "minutes": minutes,
            "title": contract.get("session_title", "Session"),
            "ts": time.time(),
        }))

        context = format_contract_context(contract)
        print(json.dumps({"additionalSystemPrompt": context}))
        return

    # ── Subsequent messages: re-inject contract + check drift ────────────────
    if existing.get("_skipped"):
        sys.exit(0)

    keywords    = existing.get("domain_keywords", [])
    prompt_low  = prompt.lower()
    is_new_task = is_task_intent(prompt_low)
    drift       = drift_score(prompt_low, keywords)

    # Only flag drift on explicit new-task prompts with high keyword divergence
    if is_new_task and drift >= 0.85 and len(keywords) >= 3:
        warning = format_drift_warning(existing)
        contract_ctx = format_contract_context(existing)
        print(json.dumps({"additionalSystemPrompt": f"{contract_ctx}\n\n{warning}"}))
    else:
        # Light reminder — keeps Claude anchored without being noisy
        ctx = format_contract_context(existing)
        print(json.dumps({"additionalSystemPrompt": ctx}))


if __name__ == "__main__":
    main()
