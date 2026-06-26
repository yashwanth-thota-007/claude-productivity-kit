# Refine Prompt

Restructure a rough prompt into a precise, well-formed request using proven prompting techniques.

## Instructions

You are given a rough prompt in **$ARGUMENTS**. Your job is to produce a single refined version ready to submit — not explain it, not ask questions, just output the improved prompt.

Apply whichever of these are relevant (skip ones that add no value for this prompt):

1. **Context** — add who is asking, what codebase/system is involved, why this matters
2. **Examples** — if the desired output format is non-obvious, show a brief example inline
3. **Constraints** — specify format, length, scope, or what to avoid
4. **Step decomposition** — if it's a multi-step task, sequence the steps explicitly
5. **Reasoning space** — for complex problems, add "think through X before answering"
6. **Role/tone** — if a specific expertise or communication style is needed, state it

## Rules

- Output ONLY the refined prompt — no preamble, no explanation, no meta-commentary
- Preserve the user's intent exactly — clarify, don't redirect
- Don't over-engineer simple prompts — if it's already clear, make minimal changes
- Use plain prose, not bullet lists, unless the task genuinely requires structured steps
- Keep it concise — a refined prompt should rarely be more than 2× the original length

## Output format

Print the refined prompt inside a markdown code block so it's easy to copy:

```
<refined prompt here>
```

Then below it, in 1–2 lines, note what you changed and why (e.g. "Added codebase context and output format constraint. Skipped examples — task is unambiguous.").
