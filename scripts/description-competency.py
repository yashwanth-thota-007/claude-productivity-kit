#!/usr/bin/env python3
"""
UserPromptSubmit hook — fires on the FIRST prompt of each session.
Evaluates the prompt against the 3P Description framework:
  Product     — what to create (output, format, audience, style)
  Process     — how to approach it (steps, research, exploration mode)
  Performance — how to behave (tone, depth, challenge vs support)

If dimensions are underspecified, injects an additionalSystemPrompt
telling Claude to ask targeted clarifying questions before starting work.
Only fires once per session. Skips short/conversational prompts.
"""
import json, sys, time
from pathlib import Path

SEEN_FILE   = Path.home() / ".claude" / "session-3p-seen.jsonl"
SEEN_MAX    = 500
MIN_CHARS   = 40  # ignore greetings and one-liners

# Signals that a dimension is already covered in the prompt
PRODUCT_SIGNALS = [
    "create", "build", "write", "generate", "output", "produce", "make",
    "draft", "implement", "return", "give me", "show me", "i want", "i need",
    "a list", "a script", "a function", "a summary", "a plan", "an email",
    "format", "structure", "template",
]
PROCESS_SIGNALS = [
    "step by step", "first", "start by", "approach", "strategy",
    "research", "explore", "analyze", "plan", "break down", "sequence",
    "incrementally", "one at a time", "begin with", "then", "after that",
    "how to", "walk me through",
]
PERFORMANCE_SIGNALS = [
    "concise", "brief", "detailed", "thorough", "verbose", "terse",
    "ask me", "challenge", "be supportive", "collaborate", "clarify",
    "don't assume", "explain", "check with me", "interactive", "proactively",
    "without asking", "just do it", "keep it short", "in depth",
]

# These prompt patterns are conversational — skip the 3P check entirely
SKIP_PATTERNS = [
    "what is", "what's", "how does", "can you", "do you", "tell me about",
    "explain", "why is", "when did", "who is", "show me how",
    "?",  # pure question
]


def is_seen(session_id: str) -> bool:
    if not SEEN_FILE.exists():
        return False
    for line in SEEN_FILE.read_text().splitlines():
        try:
            if json.loads(line).get("sid") == session_id:
                return True
        except Exception:
            continue
    return False


def mark_seen(session_id: str):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "a") as f:
        f.write(json.dumps({"sid": session_id, "ts": time.time()}) + "\n")
    lines = SEEN_FILE.read_text().splitlines()
    if len(lines) > SEEN_MAX:
        SEEN_FILE.write_text("\n".join(lines[-SEEN_MAX:]) + "\n")


def has_signals(text: str, signals: list) -> bool:
    return any(sig in text for sig in signals)


def is_conversational(prompt_lower: str) -> bool:
    return any(prompt_lower.startswith(p) or p == "?" and prompt_lower.endswith("?")
               for p in SKIP_PATTERNS)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    prompt = hook_input.get("prompt", "").strip()

    if not session_id or len(prompt) < MIN_CHARS:
        sys.exit(0)

    if is_seen(session_id):
        sys.exit(0)

    mark_seen(session_id)

    p = prompt.lower()

    if is_conversational(p):
        sys.exit(0)

    has_product     = has_signals(p, PRODUCT_SIGNALS)
    has_process     = has_signals(p, PROCESS_SIGNALS)
    has_performance = has_signals(p, PERFORMANCE_SIGNALS)

    # All three covered — nothing to inject
    if has_product and has_process and has_performance:
        sys.exit(0)

    missing = []
    questions = []

    if not has_product:
        missing.append("Product")
        questions.append(
            "What exact output do you want? (format, length, audience, or style constraints)"
        )
    if not has_process:
        missing.append("Process")
        questions.append(
            "How should I approach this? (step-by-step, exploratory, research-first, or dive straight in)"
        )
    if not has_performance:
        missing.append("Performance")
        questions.append(
            "How do you want me to behave? (concise vs thorough, ask questions vs assume, "
            "challenge your thinking vs stay supportive)"
        )

    q_lines = "\n".join(f"- {q}" for q in questions)
    advice = (
        f"[DESCRIPTION COMPETENCY — missing: {', '.join(missing)}]\n\n"
        f"The user's request doesn't fully specify: {', '.join(missing)}.\n\n"
        f"If this is a non-trivial task (not a quick factual answer), open your response "
        f"with a single friendly message asking ALL of the following at once — never split "
        f"them across turns:\n{q_lines}\n\n"
        f"If the request is clearly simple or self-contained, skip the questions and proceed."
    )

    print(json.dumps({"additionalSystemPrompt": advice}))


if __name__ == "__main__":
    main()
