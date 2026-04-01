# CLAUDE.md — Lane H: Planner

## Your Task
Create `src/fracture/planner.py`. Orchestrates LLM Call 2 (PLAN). Read PLAN.md.

## Rules
- Use build_plan_prompt from fracture.prompts
- Call model.call_json() and parse plan_md per unit
- Validate plan length (max 150 lines)

## Do NOT
- Call TerseContext directly — context is passed in
- Handle recursion or dependency logic
