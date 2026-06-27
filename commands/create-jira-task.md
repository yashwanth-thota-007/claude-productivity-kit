---
allowed-tools: Read, Glob, Bash, mcp__atlassian__*
argument-hint: [task-summary] or [epic-key] [task-summary]
description: Create a refined JIRA task with proper formatting, code references, and design links
model: opus
---

# Create JIRA Task

Create a JIRA task: $ARGUMENTS

## Current Context Discovery

- Working directory: !`pwd`
- Current branch: !`git branch --show-current`
- Git remote: !`git remote get-url origin`
- Recent commits: !`git log --oneline -5`
- Project info: @package.json or @Cargo.toml or @pom.xml (if exists)

## Task Requirements

Follow this systematic approach to create a well-structured JIRA task:

1. **Parse Arguments**
   - If first argument matches epic key pattern (e.g., CLG-8657, PROJECT-1234): use as epic key, remaining arguments as task summary
   - Otherwise: all arguments are task summary, create task without epic
   - Remaining arguments: Task summary/description

2. **Extract Project Context**
   - Detect repository name and organization from git remote
   - Identify project structure and technology stack
   - Find project-specific patterns and conventions

3. **Understand the Feature Context**
   - Analyze the feature requirements from user input
   - Review related design files (Figma links, PNG files in repo)
   - Identify affected components in the codebase
   - Find similar existing implementations for reference

4. **Research Existing Patterns**
   - Search for similar components/features in the codebase
   - Identify composables, utilities, or patterns to reuse
   - Find validation patterns, form handling approaches
   - Locate relevant test patterns

5. **Generate GitHub Links**
   - Extract org/repo from git remote
   - Convert file paths to GitHub URLs: https://github.com/{org}/{repo}/blob/{branch}/...
   - Include line number references for specific implementations
   - Link to relevant patterns as examples
   - Reference composables or utilities to reuse

6. **Structure the JIRA Description**

Use this format with h3 headers (###):

### The Why
- Explain business context and user need
- Reference current state and limitations
- Explain why this change is needed now

### The What
- Core requirements (bulleted list)
- Key functionality to implement
- Clearly mark "Stretch" goals separately

### Implementation Details
**Component Updates:**
- List new files to create with brief purpose
- List existing files to modify
- Reference existing patterns with GitHub links
- Suggest composable creation opportunities

**Similar Patterns:**
- Link to existing implementations: [description](github-url)
- Reference form validation examples
- Link to relevant utilities/composables

**API/Data Integration:**
- GraphQL mutations/queries needed (if applicable)
- Error handling approach
- Optimistic update patterns

**Stretch Goals:**
- Advanced features (drag-and-drop, animations, etc.)
- Link to library documentation or articles

**Design References:**
- Organize by viewport (mobile/tablet, desktop)
- Organize by mode (read-only, edit-mode, modal)
- Provide Figma links for each variant (if available)

### Acceptance Criteria
- Core functionality requirements (bullet points)
- User interaction flows
- Validation and error handling
- Responsive behavior across viewports
- Distinguish core from stretch goals

### Definition of Done
- Testing on testing/staging environment
- Test coverage (unit/integration/E2E as appropriate)
- Analytics events implemented (if applicable)
- Internationalization strings created (if applicable)
- Documentation updates (if needed)

## JIRA Creation Guidelines

**Formatting Rules:**
1. Use h3 (###) for all section headers
2. Use bullet points for lists, not numbered lists
3. Keep sections concise - avoid repetition
4. Use **bold** for subsection emphasis
5. Use `code blocks` for technical terms

**Code References:**
- Always provide GitHub links, not just file paths
- Include line numbers when referencing specific implementations
- Link to composables, utilities, and test helpers
- Reference validation patterns from existing code

**Design Links:**
- Include Figma links organized by viewport and mode
- Reference design files in repo if available

**Avoid Repetition:**
- Don't repeat requirements across sections
- Keep "The What" high-level
- Put technical details in "Implementation Details"
- Keep Definition of Done concise

## Execution Steps

1. Parse arguments to detect optional epic key (matches PROJECT-#### pattern)
2. Detect project context (org, repo, technology)
3. Authenticate with Atlassian if needed
4. Get cloud ID and verify epic exists (if epic key provided)
5. Research codebase for similar patterns
6. Generate GitHub links using detected org/repo
7. Structure description following guidelines
8. Create issue with epic linking (if epic key provided) or standalone task
9. Return ticket URL and key

Remember: The goal is to create a clear, actionable ticket that a developer can pick up and implement without ambiguity, while keeping it concise and non-repetitive.
