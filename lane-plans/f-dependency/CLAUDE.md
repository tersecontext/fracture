# CLAUDE.md — Lane F: Dependency Engine

## Your Task
Create `src/fracture/dependency.py`. Pure graph logic for write-set overlap, dependency derivation, validation, phase calculation, and dependency rewiring. Read PLAN.md for function specs.

## Rules
- Import types from fracture.types only
- All functions are pure — no I/O, no API calls, no side effects
- Use BFS/DFS for path checking
- Topological sort for phase calculation

## Do NOT
- Call LLMs or TerseContext
- Touch the filesystem or bd CLI
