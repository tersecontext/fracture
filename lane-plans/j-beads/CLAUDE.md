# CLAUDE.md — Lane J: Beads CLI Integration

## Your Task
Create `src/fracture/beads.py`. All `bd` CLI interaction for the project. Read PLAN.md for the full interface.

## Rules
- asyncio.create_subprocess_exec for shell commands
- Always use --json flag on bd commands
- Use stdin or --body-file for long content to avoid escaping issues
- Transactional: if any create fails, close all previously created beads

## Do NOT
- Import from other fracture modules besides types
- Call LLMs or TerseContext
- Touch the Dolt database directly — always go through bd CLI
