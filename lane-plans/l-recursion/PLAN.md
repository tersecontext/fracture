# Lane L: Recursion Engine

## File
`src/fracture/recursion.py`

## Depends On
- Lane G (analyzer) — re-analyzes compound beads
- Lane F (dependency) — rewires dependencies, re-derives phases

## What to Build
Detects compound units, recursively decomposes them, replaces them in the graph with sub-units, and rewires all dependencies.

## Interface
```python
class RecursionEngine:
    def __init__(self, analyzer: Analyzer, config: FractureConfig):
        pass

    async def process(self, units: list[Unit], edges: list[DependencyEdge],
                      project: str, depth: int = 0) -> tuple[list[Unit], list[DependencyEdge]]:
        """
        For each unit, check if compound.
        If compound and depth < max_recursion_depth:
          - Re-analyze with narrower scope
          - Replace unit with sub-units
          - Rewire dependencies via dependency.rewire_dependencies()
          - Recurse on sub-units
        Returns the final flat list of atomic units and edges.
        """
```

## Compound Detection
A unit is compound if ANY:
- `len(manifest.creates) + len(manifest.modifies) > 6`
- `estimated_hours > config.max_bead_hours`
- Files span 3+ distinct top-level directories
- Description contains sequential phases ("first... then... finally...")

## Recursion Rules
- Max depth from config (default 4)
- At max depth, log warning and keep unit as-is
- Each recursion narrows the TerseContext query to only the files in the compound unit's manifest
- Sub-units inherit parent's incoming dependencies
- Parent's downstream dependents wait for ALL sub-units (conservative) or the specific sub-unit that produces the needed files (optimized — check write set intersection)

## Dependency Rewiring Detail
```
Before: X → P → Y  (X blocks P, P blocks Y)
After splitting P into S1, S2, S3:
  X → S1, X → S2, X → S3  (X blocks all sub-units)
  
  For Y: check which sub-unit writes files that Y reads
    If S2 writes auth.js and Y reads auth.js → S2 → Y
    If unclear → S1,S2,S3 → Y (conservative)
```

## Completion Criteria
- Compound detection catches all signals
- Recursion produces atomic sub-units
- Dependencies are correctly rewired
- Depth limit is respected
- Returns a flat unit list (no nesting)

## When Done
```bash
bd close <ID> "Recursion engine complete, rewiring tested"
```
Unblocks: Lane N (server orchestrates the full pipeline including recursion)
