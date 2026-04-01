# Lane J: Beads CLI Integration

## File
`src/fracture/beads.py`

## Depends On
- Lane A (types)

## What to Build
All interaction with the `bd` CLI. No other module calls `bd` directly. Handles transactional bead creation with rollback on failure.

## Interface
```python
class BeadsClient:
    def __init__(self, project_dir: str):
        """Set working directory for bd commands."""

    async def create_bead(self, title: str, bead_type: str, priority: int,
                          deps: list[str], description: str, design: str,
                          acceptance: str, notes: str) -> str:
        """Create a bead via bd create. Returns the bead ID.
        Uses --json flag to parse output."""

    async def close_bead(self, bead_id: str, reason: str) -> bool:
        """Close a bead via bd close."""

    async def show_bead(self, bead_id: str) -> dict:
        """Get bead details via bd show --json."""

    async def list_open_beads(self, decomposition_id: str | None = None) -> list[dict]:
        """List open beads, optionally filtered by decomposition_id in notes."""

    async def create_beads_transactional(self, beads: list[dict]) -> list[str]:
        """Create all beads in topological order.
        If any creation fails, close all previously created beads
        with 'decomposition failed — partial cleanup' reason.
        Returns list of created bead IDs."""
```

## bd CLI Commands Used
```bash
bd create "$title" -t $type -p $priority \
  --deps blocks:$dep1,blocks:$dep2 \
  --description="$desc" --design="$design" \
  --acceptance="$acc" --notes="$notes" --json

bd close $id --reason "$reason" --json

bd show $id --json

bd list --status open --json
```

## Shell Execution
- Use asyncio.create_subprocess_exec
- Capture stdout/stderr
- Parse JSON output
- For long description/design content, use `--body-file` with temp files or stdin piping to avoid shell escaping issues

## Completion Criteria
- All CRUD operations work against bd CLI
- Transactional creation rolls back on failure
- JSON parsing of bd output is reliable
- Shell escaping handled for multi-line content

## When Done
```bash
bd close <ID> "Beads client complete, transactional creation tested"
```
Unblocks: Lane M (feedback needs beads), Lane N (server needs beads)
