# Lane G: Analyzer (LLM Call 1)

## File
`src/fracture/analyzer.py`

## Depends On
- Lane C (tersecontext) — queries codebase context
- Lane D (model) — makes LLM call
- Lane E (prompts) — gets ANALYZE prompt
- Lane A (types) — uses Unit, FileManifest, CodebaseContext

## What to Build
Orchestrates Call 1 (ANALYZE): queries TerseContext, builds the prompt, calls the model, parses and validates the response, handles correction rounds.

## Interface
```python
class Analyzer:
    def __init__(self, tc_client: TerseContextClient, model: ModelClient, config: FractureConfig):
        pass

    async def analyze(self, task: str, project: str, 
                      artifacts: list[dict] | None = None) -> list[Unit]:
        """
        1. Query TerseContext for context (or use artifacts fallback)
        2. Build ANALYZE prompt
        3. Call model.call_json()
        4. Parse response into list[Unit]
        5. Validate file paths against file tree
        6. Fix creates/modifies misclassification
        7. If validation fails, send correction prompt (max N rounds)
        8. Return validated units
        """
```

## Validation Rules
1. All paths in `modifies` must exist in TerseContext file tree
2. All paths in `creates` must NOT exist in file tree (move to modifies if they do)
3. `estimated_hours` must be > 0
4. Each unit must have at least one file in creates or modifies
5. JSON must match expected schema

## Correction Prompt
```
Your previous decomposition had issues:
- {path} listed in modifies but does not exist in the codebase
- {path} listed in creates but already exists — moved to modifies
- Unit "{title}" has no files in creates or modifies

Please fix and respond with the corrected JSON.
```

Max correction rounds from config (default 2). After that, raise AnalysisError.

## Completion Criteria
- Queries TerseContext and builds context
- Falls back to inline artifacts when TerseContext unavailable
- Calls model and parses JSON response
- Validates all file paths
- Correction rounds work
- Returns clean list[Unit]

## When Done
```bash
bd close <ID> "Analyzer complete, validation and correction working"
```
Unblocks: Lane L (recursion calls analyzer)
