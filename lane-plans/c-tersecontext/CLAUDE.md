# CLAUDE.md — Lane C: TerseContext Client

## Your Task
Create `src/fracture/tersecontext.py`. Client for querying TerseContext codebase knowledge graph. Read PLAN.md for the full API contract.

## Rules
- Async (aiohttp or httpx)
- Import CodeResult, DependencyGraphEdge, CodebaseContext from fracture.types
- Graceful fallback when TerseContext is unreachable
- No retries — just return empty context on failure

## Do NOT
- Import from other fracture modules besides types
- Call LLMs — this is a data client only
