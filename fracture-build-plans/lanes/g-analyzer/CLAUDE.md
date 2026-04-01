# CLAUDE.md — Lane G: Analyzer

## Your Task
Create `src/fracture/analyzer.py`. Orchestrates LLM Call 1 (ANALYZE). Read PLAN.md for full spec.

## Rules
- Import TerseContextClient, ModelClient, types from respective modules
- Use build_analyze_prompt from fracture.prompts
- Validate all file paths against TerseContext file tree
- Max correction rounds from config
- Async throughout

## Do NOT
- Call bd CLI — that's beads.py
- Write logs — that's logger.py
- Handle recursion — that's recursion.py
