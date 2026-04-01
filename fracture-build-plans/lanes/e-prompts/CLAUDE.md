# CLAUDE.md — Lane E: Prompt Templates

## Your Task
Create `src/fracture/prompts.py`. Three prompt builder functions for the ANALYZE, PLAN, and INSTRUCT LLM calls. Read PLAN.md for specs. The exact system prompt text is in FRACTURE_PLAN_V2.md.

## Rules
- Import types from fracture.types
- Each function returns (system_prompt: str, user_message: str)
- System prompts are string constants at module level
- User messages are assembled from the provided context

## Do NOT
- Make API calls — these just build prompt strings
- Import from other fracture modules besides types
