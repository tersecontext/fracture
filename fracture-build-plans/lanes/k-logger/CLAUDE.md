# CLAUDE.md — Lane K: Audit Logger

## Your Task
Create `src/fracture/logger.py`. Append-only JSONL log writer. Read PLAN.md.

## Rules
- Import types from fracture.types only
- JSONL format — one JSON object per line
- Create log directory if missing
- All writes are appends — never overwrite

## Do NOT
- Read logs (that's for humans/other tools)
- Import from other fracture modules besides types
