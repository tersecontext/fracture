# Lane H: Planner (LLM Call 2)

## File
`src/fracture/planner.py`

## Depends On
- Lane D (model), Lane E (prompts), Lane A (types)

## What to Build
Orchestrates Call 2 (PLAN): takes analyzed units + dependency graph + TerseContext excerpts, calls the model, returns plan_md content per unit.

## Interface
```python
class Planner:
    def __init__(self, model: ModelClient):
        pass

    async def generate_plans(self, units: list[Unit], edges: list[DependencyEdge],
                             context: CodebaseContext) -> list[str]:
        """Returns list of plan_md strings, one per unit, in order."""
```

## Validation
- Each plan must be under 150 lines
- Each plan must reference at least one file from the unit's manifest
- JSON response must have one entry per unit

## Completion Criteria
- Generates plan_md for each unit
- Plans are specific (reference real file paths, not generic)
- Under 150 lines each

## When Done
```bash
bd close <ID> "Planner complete, generates specific plans"
```
Unblocks: Lane N (server needs planner)
