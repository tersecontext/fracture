# CLAUDE.md — Lane A: Core Types

## Project
Fracture — task decomposition engine for beads.

## Your Task
Create `src/fracture/types.py` with all shared data types. Read PLAN.md for the full schema.

## Rules
- Python dataclasses or pydantic models
- Every type must have `to_json()` and `from_json()` class methods
- No external dependencies beyond standard library and pydantic
- This file is imported by every other module — keep it clean

## Do NOT
- Import from any other fracture module
- Make API calls
- Add business logic — these are pure data types
