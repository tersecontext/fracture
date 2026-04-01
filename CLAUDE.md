# CLAUDE.md — Fracture

## What is Fracture?
An MCP server that decomposes large tasks into dependency-ordered beads. It queries TerseContext for codebase intelligence, calls an LLM (Claude API or local) to reason about decomposition, splits work along file boundaries to prevent merge conflicts, and creates beads in `bd`.

Fracture does NOT execute beads, manage worktrees, or spawn agents.

## Task Management
This project uses **beads** (`bd`) for all task tracking.
- `bd ready --json` — find available work
- `bd update <id> --claim` — claim a task
- `bd close <id> "reason"` — complete a task

## Architecture
```
src/fracture/
├── types.py          # Core data types and schemas
├── config.py         # YAML config parser
├── tersecontext.py   # TerseContext query client
├── model.py          # LLM client (Claude API + local/OpenAI-compatible)
├── prompts.py        # Three prompt templates (ANALYZE, PLAN, INSTRUCT)
├── dependency.py     # Write-set overlap, graph validation, phase calculation
├── analyzer.py       # Call 1 orchestration + output validation
├── planner.py        # Call 2 orchestration (plan generation)
├── instructor.py     # Call 3 orchestration (CLAUDE.md generation)
├── recursion.py      # Compound detection, sub-decomposition, dependency rewiring
├── beads.py          # bd CLI integration, transactional bead creation
├── logger.py         # Audit log writer
├── feedback.py       # Post-execution accuracy reporting
└── server.py         # MCP server exposing decompose/validate/further_decompose/feedback
```

## Tech Stack
- Python (primary language)
- MCP SDK for Python (FastMCP)
- Claude API (anthropic SDK) + OpenAI-compatible endpoint for local models
- beads (`bd` CLI) for task creation
- TerseContext for codebase queries

## Key Rules
- Each module is one file
- Modules communicate through types defined in types.py
- LLM calls go through model.py — no direct API calls from other modules
- All bd interaction goes through beads.py — no direct CLI calls from other modules
- Structured JSON in the notes field for file manifests (see types.py for schema)
- Log directory defaults to .fracture/logs/ relative to project root
