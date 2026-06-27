# Prime - Project Context Initialization

Initialize a new Claude Code session with comprehensive project context.

*Command originally created by IndyDevDan (YouTube: https://www.youtube.com/@indydevdan) / DislerH (GitHub: https://github.com/disler)*

## Instructions

Initialize a new Claude Code session with comprehensive project context:

1. **Analyze Codebase Structure**
   - Run `git ls-files` to understand file organization and project layout
   - Execute directory tree commands (if available) for visual structure
   - Identify key directories and their purposes
   - Note the technology stack and frameworks in use
   - Identify testing frameworks and patterns (unit, integration, E2E)
   - Check for CODEOWNERS file location and format

2. **Read Project Documentation**
   - Read README.md for project overview and setup instructions
   - Check for any additional documentation in docs/ or ai_docs/
   - Review any CONTRIBUTING.md or development guides
   - Look for architecture or design documents
   - Check for API documentation or OpenAPI/Swagger specs
   - Review code style guides or linting configurations

3. **Understand Project Context**
   - Identify the project's primary purpose and goals
   - Note any special setup requirements or dependencies
   - Check for environment configuration needs
   - Review any CI/CD configuration files
   - Identify common code patterns and conventions
   - Note package manager (npm, yarn, pnpm, pip, cargo, etc.)
   - Check for monorepo structure (if applicable)

4. **Analyze Development Workflow**
   - Check git branch strategy and naming conventions
   - Review PR/merge request templates
   - Note any pre-commit hooks or git hooks
   - Identify deployment processes and environments

5. **Save Results and Output Summary**
   - **CRITICAL: Create or update `.claude/prime-results.md` in the project root** with all findings
   - Use the Write tool to save a comprehensive markdown document including:
     - Project Overview: purpose, goals, and description (2-3 sentences)
     - Technology Stack: main technologies, frameworks, and tools
     - Project Structure: key directories and their purposes
     - Testing Strategy: frameworks used (unit, integration, E2E) and patterns
     - Development Workflow: branch strategy, PR process, git hooks
     - Build & Deploy: common commands (build, test, lint, deploy, start)
     - Code Conventions: coding standards, patterns, and style guides
     - Configuration: environment setup, package manager, special requirements
     - Documentation: locations of key docs, API specs, architecture diagrams
     - Code Ownership: CODEOWNERS file location and ownership patterns
     - Last Updated: timestamp of when prime was run
   - After saving, provide a brief summary to the user of key findings

This command helps establish context quickly when:
- Starting work on a new project
- Returning to a project after time away
- Onboarding new team members
- Preparing for deep technical work
- Beginning a new Claude Code session

The goal is to "prime" the AI assistant with essential project knowledge for more effective assistance.

## Result Storage

The results are saved to `.claude/prime-results.md` at the root of the project directory (NOT the user home `.claude/` folder). This file should be:
- Created in the current working directory's `.claude/` folder
- Updated each time `/prime` is run
- Referenced at the start of new sessions for context continuity
- Version controlled if the team wants to share project context

## Usage in Future Sessions

When starting a new Claude Code session in this project:
1. Check if `.claude/prime-results.md` exists
2. Read it to quickly understand the project structure and conventions
3. Use this context as the foundation for all work
4. Re-run `/prime` if the project has changed significantly or the file is outdated