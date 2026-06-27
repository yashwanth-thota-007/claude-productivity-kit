# User-Level Custom Instructions

**CRITICAL**: Throughout this document, `.claude/` **always** refers to the **local project's `.claude/` folder** (in the working directory), **NOT** the user-level `~/.claude/` folder. All files, tasks, and documentation must be created in the project's local `.claude/` directory.

## Context Understanding

At the start of every new session:
1. **Read `<project-root>/.claude/prime-results.md` first** if it exists to understand project context
2. Review the file to understand project structure, conventions, and patterns
3. **Scan `<project-root>/.claude/docs/`** if it exists — read any markdown files there to load system architecture, flow diagrams, and domain knowledge into context before starting work
4. Use this context as the foundation for all work in the session

When starting work on any task:
1. Assess whether you have sufficient context about the project, codebase, or task requirements
2. If context is lacking or unclear, run the `/prime` command to understand the project structure, conventions, and patterns
3. **Update or create`.claude/prime-results.md`** with the new context from `/prime`
4. Use the information gathered to align your work with existing patterns
5. If `/prime` is not available or doesn't provide sufficient context, use appropriate exploration tools

## Persistent Context Updates

**When you discover missing or new knowledge during a session, write it to docs so future sessions inherit it.**

Whenever you learn something about the project that isn't already captured — architecture decisions, non-obvious conventions, environment quirks, domain knowledge, API contracts, data models, deployment details — persist it immediately:

- **General project knowledge** → append to or update `<project-root>/.claude/prime-results.md`
- **Topic-specific knowledge** (e.g., auth flow, DB schema, service boundaries) → create or update a focused file in `<project-root>/.claude/docs/<topic>.md`

Triggers that should cause a context write:
- You had to explore or infer something that `/prime` didn't cover
- You found a pattern, constraint, or convention that isn't obvious from the code
- You resolved an ambiguity by asking the user — the answer belongs in docs
- You discovered how a subsystem works while debugging or implementing
- The user corrects a wrong assumption you made — capture the truth

Keep entries concise and factual. No commentary, no "as of today" hedges — just durable facts a future session can act on. Do this proactively; don't wait for the user to ask.

## Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## Code Review Before Execution

Before writing, editing, or creating any files, you MUST:
1. Review the code you're about to write
2. Consider the impact on the existing codebase
3. Verify that the changes align with the user's requirements
4. Check for potential issues, bugs, or conflicts
5. Only proceed with file operations after this review

## Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

Every changed line should trace directly to the user's request.

## Automatic Checkpoints

Create automatic git checkpoints (commits) in the following situations:
- When you receive positive feedback like "looks good", "LGTM", "great", "perfect"
- After completing incremental requests or subtasks
- After successfully implementing a feature or fixing a bug
- Before starting major refactoring or significant changes

When creating checkpoints:
- Run `git diff --staged` to review the diff before committing — confirm every changed line is intentional
- Cross-check the diff against the original goal: every change must trace to the task. Flag anything that doesn't.
- **Always confirm with the user before committing** — summarize what will be committed and why, then wait for explicit approval
- Use descriptive commit messages that explain what was accomplished
- Include the 🤖 Claude Code attribution
- Run `git status` to verify the changes before committing

## Incremental Work Pattern

When working on complex tasks:
1. Break down the work into smaller, logical steps
2. Complete one step at a time
3. Verify each step before moving to the next
4. Create checkpoints after each successful step
5. Update the todo list to track progress

## Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria enable independent looping. Weak criteria ("make it work") require constant clarification.

## Testing Requirements

For every new function, method, or module you write, you MUST write tests alongside the code — not as an afterthought:
- **Write tests as you write code**, not retroactively. New code without tests is not done.
- **Analyze the project setup** first to understand the testing framework and patterns used
- Write **unit tests** for individual functions, methods, and components
- Write **integration tests** for interactions between modules or services
- Write **E2E tests** (end-to-end) for critical user flows if the project has E2E testing setup
- Follow the existing test structure, naming conventions, and patterns in the project
- Ensure tests cover:
  - Happy path scenarios
  - Edge cases and error conditions
  - Boundary conditions
  - Integration points
- **Tests must be meaningful** — they must assert real, specific behavior:
  - Assert concrete return values, state changes, or side effects
  - No placeholder tests (`assert true`, empty bodies, `pass`)
  - No trivial smoke tests that only check "it didn't throw"
  - If you can't think of a meaningful assertion, the code design may need rethinking
- Run tests to verify they pass before considering the task complete
- Include test writing in your todo list and checkpoints

## File Organization

**ALL files must be created in the local project's `.claude/` directory**, NOT in `~/.claude/`:

When creating documentation, temporary files, or working files:
- **Location**: `<project-root>/.claude/` (the `.claude/` folder in your current working directory)
- **NEVER use**: `~/.claude/` or `/Users/username/.claude/` for project files

**Task Organization**:
- Create a separate folder for each task under `<project-root>/.claude/tasks/`
  - **Naming convention**: `<project-root>/.claude/tasks/DD-MM-YYYY-[task-title]/`
  - Examples:
    - `<project-root>/.claude/tasks/26-11-2025-authentication/`
    - `<project-root>/.claude/tasks/26-11-2025-api-migration/`
    - `<project-root>/.claude/tasks/26-11-2025-dark-mode-feature/`
  - Each task folder should contain its own:
    - `docs/` - Documentation for the task
    - `notes/` - Planning, analysis, and investigation notes
    - `temp/` - Temporary or scratch files
    - `tests/` - Test files before moving to proper location
  - This keeps work organized by task/feature and chronologically ordered

**Prime Results Storage**:
- **Store `/prime` command output** in `<project-root>/.claude/prime-results.md`
  - Update this file each time `/prime` is run
  - Keep the most recent context understanding documented
  - Reference this file when starting new tasks

**Important**:
- Ensure the necessary directories exist before creating files
- This keeps the project root clean and work organized
- All project-specific files stay with the project, not in your user directory

## Documentation Updates

When making major changes, you MUST update or create documentation:
- Update existing documentation (README, API docs, architecture docs) to reflect the changes
- Create new documentation for significant new features or systems
- Document breaking changes, migration steps, or deprecated functionality
- Update code examples and usage instructions if they're affected
- Place documentation in `<project-root>/.claude/tasks/DD-MM-YYYY-[task-title]/docs/` during development, then move to proper location when complete

Major changes that require documentation updates include:
- New features or major feature enhancements
- API changes or new endpoints
- Architecture or design pattern changes
- Configuration or environment changes
- Breaking changes or deprecations

## CODEOWNERS Maintenance

When adding new files or directories, update the CODEOWNERS file:
- Check if a `CODEOWNERS` file exists (typically in `.github/CODEOWNERS`, `docs/CODEOWNERS`, or root `CODEOWNERS`)
- Add ownership rules for new files, directories, or modules
- Follow the existing pattern and format in the CODEOWNERS file
- Assign ownership based on:
  - Team responsible for the feature/module
  - Area of expertise (frontend, backend, infrastructure, etc.)
  - Existing ownership patterns in the codebase
- Ensure ownership rules are specific enough to route reviews correctly
- If unsure about ownership, ask the user or check existing similar files for guidance

## Code Comments Policy

- **NO trivial comments** - Do not add comments for obvious, self-explanatory code
- Only add comments for complex, non-readable, or non-obvious code logic
- Comments should explain "why" not "what" when the code is complex
- Prefer writing clear, self-documenting code over adding comments
- Examples of when to comment:
  - Complex algorithms or mathematical operations
  - Non-obvious business logic or edge cases
  - Workarounds for bugs or limitations
  - Performance optimizations that aren't immediately clear

## Code Quality - DRY Principle

**NO duplicate code** - Follow the DRY (Don't Repeat Yourself) principle:
- Before writing new code, check if similar functionality already exists
- Extract repeated logic into reusable functions, methods, or utilities
- Create shared components, modules, or libraries for common patterns
- Refactor duplicate code when discovered during implementation
- Use abstraction and composition to eliminate repetition
- If code appears similar but serves different purposes, add comments explaining why duplication is justified

## Tool and Agent Selection

Choose appropriate tools, agents, commands, and MCP servers based on the task and project:
- **Analyze the task requirements** before selecting tools
- Use specialized agents (frontend-developer, backend-architect, debugger, etc.) when their expertise matches the task
- Leverage available slash commands that align with the task (e.g., /code-review, /generate-tests, /architecture-review)
- Utilize MCP servers (GitHub, Datadog, Atlassian, Playwright, etc.) when they provide relevant functionality
- Use the Explore agent for codebase discovery and understanding
- Prefer specialized tools over generic ones when available
- Don't default to the same tools every time - assess what's most appropriate for each specific task

## Command Usage Guidelines for Full-Stack Senior Engineer

Proactively use these commands in your workflow:

**Code Quality & Review:**
- Use `/code-review` for general code quality analysis (security, performance, architecture)
- Use `/pr-review` for comprehensive multi-perspective PR reviews before merging
- Use `/architecture-review` when evaluating system design or planning major refactors

**Testing:**
- Use `/write-tests` for generating unit, integration, or E2E tests after implementing features
- Use `/test-coverage` to analyze and improve test coverage gaps
- Prefer `/write-tests` over `/generate-tests` (they are duplicates, use write-tests)

**Documentation & Task Management:**
- Use `/prime` at the start of work in new projects or after long breaks
- Use `/update-docs` when making major changes that affect documentation
- Use `/create-jira-task` for creating well-structured, detailed JIRA tickets

**When to skip commands:**
- Don't use commands for trivial tasks that can be done directly
- Skip `/create-pull-request` - use git/gh CLI directly instead
- Avoid overly complex commands like `/workflow-orchestrator` - break into smaller tasks

## Context Window Management

Monitor and manage context window usage:
- **Auto-compact when reaching 95%** of context window capacity
- **Compact before starting any new major task** to ensure sufficient space
- When compacting, preserve:
  - Current task context and requirements
  - Key decisions and rationale
  - Important code references
  - Open todos and next steps
- Use `/compact` command or appropriate compaction method
- After compacting, verify that essential context is retained

## General Guidelines

- Prefer editing existing files over creating new ones
- Always use the TodoWrite tool for multi-step tasks
- Keep the user informed of progress
- Ask for clarification when requirements are ambiguous
- Test code mentally before writing it to the workspace
