# Lane E: Prompt Templates

## File
`src/fracture/prompts.py`

## Depends On
- Lane A (types) — uses Unit, FileManifest, CodebaseContext schemas in prompts

## What to Build
Three prompt template functions, one per LLM call. Each returns a `(system_prompt, user_message)` tuple.

## Functions

### build_analyze_prompt
```python
def build_analyze_prompt(task: str, context: CodebaseContext) -> tuple[str, str]:
    """Call 1: ANALYZE. Returns (system_prompt, user_message).
    System prompt defines the staff engineer role and Unit JSON schema.
    User message contains the task + file tree + relevant code + dependency graph."""
```

### build_plan_prompt
```python
def build_plan_prompt(units: list[Unit], edges: list[DependencyEdge], context: CodebaseContext) -> tuple[str, str]:
    """Call 2: PLAN. Returns (system_prompt, user_message).
    System prompt defines plan writing rules (~150 lines per plan).
    User message contains units with manifests, dependency graph, code excerpts."""
```

### build_instruct_prompt
```python
def build_instruct_prompt(units: list[Unit], plans: list[str], context: CodebaseContext) -> tuple[str, str]:
    """Call 3: INSTRUCT. Returns (system_prompt, user_message).
    System prompt defines CLAUDE.md writing rules (~50 lines per instruction set).
    User message contains units, plans, relevant code context."""
```

## Prompt Content
The exact system prompts are specified in FRACTURE_PLAN_V2.md under the "Prompts" section. Copy them verbatim into this module as string constants, then use them in the builder functions.

## User Message Assembly
Each user message assembles context from CodebaseContext:
- File tree as ASCII listing
- Code excerpts with `--- path ---` headers
- Dependency edges as `from → to (type)` listings
- Architecture summary as prose

## Completion Criteria
- All three functions return well-formed (system, user) tuples
- System prompts include exact JSON output schemas
- User messages include all relevant context sections
- Prompts tested manually by pasting into Claude/ChatGPT

## When Done
```bash
bd close <ID> "All three prompts complete, manually tested"
```
Unblocks: Lanes G, H, I (analyzer, planner, instructor need prompts)
