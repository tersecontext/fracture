# CLAUDE.md — Lane L: Recursion Engine

## Your Task
Create `src/fracture/recursion.py`. Detects compound units, recursively decomposes, rewires dependencies. Read PLAN.md for compound detection rules and rewiring logic.

## Rules
- Import Analyzer from fracture.analyzer
- Import derive_dependencies, rewire_dependencies from fracture.dependency
- Respect max_recursion_depth from config
- Output is always a flat list — no nested structures

## Do NOT
- Call bd CLI — that happens after recursion
- Generate plans or instructions — that's planner/instructor
- Write logs — that's logger
