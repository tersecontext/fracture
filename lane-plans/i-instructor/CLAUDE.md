# CLAUDE.md — Lane I: Instructor

## Your Task
Create `src/fracture/instructor.py`. Orchestrates LLM Call 3 (INSTRUCT). Read PLAN.md.

## Rules
- Use build_instruct_prompt from fracture.prompts
- Call model.call_json() and parse claude_md per unit
- Each instruction set must be self-contained for an isolated agent

## Do NOT
- Call TerseContext directly — context is passed in
- Handle recursion or dependency logic
