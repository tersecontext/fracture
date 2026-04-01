# Lane F: Dependency Engine

## File
`src/fracture/dependency.py`

## Depends On
- Lane A (types)

## What to Build
Pure functions for write-set overlap detection, dependency graph construction, graph validation, and phase calculation. No LLM calls, no I/O — this is deterministic graph logic.

## Functions

```python
def derive_dependencies(units: list[Unit]) -> list[DependencyEdge]:
    """For each pair of units, check if their write sets overlap.
    If overlap: create a dependency edge from the logically earlier to the later.
    Ordering heuristic: creates-only units before modify units, lower index first."""

def validate_graph(units: list[Unit], edges: list[DependencyEdge]) -> list[tuple[int, int, set[str]]]:
    """Check all pairs with NO dependency path between them.
    If their write sets overlap, return them as conflicts.
    Empty list = valid graph."""

def determine_phases(units: list[Unit], edges: list[DependencyEdge]) -> list[Phase]:
    """Topological sort by dependency depth.
    Phase 1: units with no incoming edges (roots).
    Phase N: units whose deps are all in phases < N.
    Returns list of Phase objects."""

def has_dependency_path(a: int, b: int, edges: list[DependencyEdge]) -> bool:
    """BFS/DFS: is there a directed path from a to b (or b to a) in the edge graph?"""

def rewire_dependencies(parent_idx: int, sub_units: list[Unit], 
                        existing_edges: list[DependencyEdge]) -> list[DependencyEdge]:
    """When a parent unit is replaced by sub-units during recursion:
    - Everything that blocked parent now blocks all sub-units
    - Everything parent blocked now waits for the last sub-unit
      (or the specific sub-unit that produces the needed files)
    Returns the updated edge list with parent removed."""
```

## Completion Criteria
- derive_dependencies correctly identifies all write overlaps
- validate_graph catches conflicts between unrelated parallel units
- determine_phases produces correct topological ordering
- rewire_dependencies correctly transfers edges during recursion
- All functions are pure — no side effects

## When Done
```bash
bd close <ID> "Dependency engine complete, all graph operations tested"
```
Unblocks: Lane L (recursion needs dependency logic)
