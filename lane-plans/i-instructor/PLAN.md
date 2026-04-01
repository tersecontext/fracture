# Lane I: Instructor (LLM Call 3)

## File
`src/fracture/instructor.py`

## Depends On
- Lane D (model), Lane E (prompts), Lane A (types)

## What to Build
Orchestrates Call 3 (INSTRUCT): takes units + plans + code context, calls the model, returns claude_md content per unit.

## Interface
```python
class Instructor:
    def __init__(self, model: ModelClient):
        pass

    async def generate_instructions(self, units: list[Unit], plans: list[str],
                                    context: CodebaseContext) -> list[str]:
        """Returns list of claude_md strings, one per unit, in order."""
```

## Validation
- Each instruction set must be under 50 lines
- Must include key files from the unit's manifest
- Must include "Do NOT" section to prevent scope creep

## Completion Criteria
- Generates claude_md for each unit
- Instructions are self-contained (agent can work from these alone)
- Under 50 lines each

## When Done
```bash
bd close <ID> "Instructor complete, generates scoped agent instructions"
```
Unblocks: Lane N (server needs instructor)
