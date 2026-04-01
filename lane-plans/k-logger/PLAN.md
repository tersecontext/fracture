# Lane K: Audit Logger

## File
`src/fracture/logger.py`

## Depends On
- Lane A (types)

## What to Build
Append-only JSONL log writer. Logs decomposition events, bead creation, feedback, and errors to `.fracture/logs/`.

## Interface
```python
class FractureLogger:
    def __init__(self, log_dir: str, project_dir: str):
        """Initialize. Creates log_dir if it doesn't exist."""

    def log_decomposition(self, task: str, model_used: str, dry_run: bool,
                          beads: list[dict], phases: list[Phase],
                          tc_queries: list[dict], validation: dict,
                          recursion_events: list[dict],
                          decomposition_id: str) -> str:
        """Write a decomposition event to the log. Returns log file path."""

    def log_feedback(self, feedback: FeedbackResult):
        """Append a feedback event to the log."""

    def log_error(self, decomposition_id: str, error: str, partial_beads: list[str]):
        """Log a failed decomposition with partial state."""

    def get_log_path(self, decomposition_id: str) -> str:
        """Return the log file path for a given decomposition."""
```

## Log Format
File: `.fracture/logs/YYYY-MM-DD-{decomposition_id}.jsonl`

Each line is a JSON object with a `type` field:
- `"type": "decomposition"` — full decomposition record
- `"type": "feedback"` — post-execution accuracy report
- `"type": "error"` — failed decomposition

All entries include `timestamp` in ISO8601.

## Log Directory
- Default: `.fracture/logs/` relative to project_dir
- Create directory if it doesn't exist
- Add `.fracture/` to .gitignore guidance in README

## Completion Criteria
- JSONL append works correctly
- Log directory created automatically
- All three event types write valid JSON
- Log path derivation is consistent

## When Done
```bash
bd close <ID> "Logger complete, all event types tested"
```
Unblocks: Lane M (feedback needs logger), Lane N (server needs logger)
