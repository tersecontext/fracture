# Lane C: TerseContext Client

## File
`src/fracture/tersecontext.py`

## What to Build
A client that queries TerseContext for codebase intelligence. Three query types: semantic_search, dependency_graph, file_tree.

## Interface

```python
class TerseContextClient:
    def __init__(self, endpoint: str):
        """Connect to TerseContext at the given endpoint."""

    async def semantic_search(self, query: str, project: str, max_results: int = 10) -> list[CodeResult]:
        """Find code relevant to a natural language query."""

    async def dependency_graph(self, paths: list[str], project: str, depth: int = 2) -> list[DependencyGraphEdge]:
        """Get import/call/test edges for the given files."""

    async def file_tree(self, project: str, path_prefix: str = "") -> list[str]:
        """Get all file paths in the project."""

    async def get_context(self, task: str, project: str) -> CodebaseContext:
        """High-level: extract topics from task, run searches, aggregate into CodebaseContext."""

    def is_available(self) -> bool:
        """Health check — is TerseContext reachable?"""
```

## Fallback
If TerseContext is unavailable, `get_context()` should return an empty CodebaseContext with `is_available() = False`. The caller (analyzer) handles the fallback to inline artifacts.

## TerseContext API
TerseContext is pre-alpha. Build against this contract:
- `POST /search` → `{query, project, max_results}` → `{results: [{path, content, score, node_type}]}`
- `POST /graph` → `{paths, project, depth}` → `{edges: [{from, to, type}]}`
- `POST /files` → `{project, path_prefix}` → `{files: [string]}`

If TerseContext exposes an MCP interface instead of REST, use the MCP client SDK.

## Completion Criteria
- All three query methods work against the defined contract
- get_context() aggregates search + graph + file tree
- Graceful fallback when TerseContext is down
- Async throughout

## When Done
```bash
bd close <ID> "TerseContext client complete, fallback working"
```
Unblocks: Lane G (analyzer needs TerseContext)
