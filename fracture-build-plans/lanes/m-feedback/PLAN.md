# Lane M: Feedback Tool

## File
`src/fracture/feedback.py`

## Depends On
- Lane J (beads) — reads bead metadata
- Lane K (logger) — writes feedback events

## What to Build
Compares predicted file manifests against actual files changed after bead execution. Logs accuracy for calibration.

## Interface
```python
class FeedbackProcessor:
    def __init__(self, beads: BeadsClient, logger: FractureLogger):
        pass

    async def process_feedback(self, bead_id: str,
                               actual_creates: list[str],
                               actual_modifies: list[str]) -> FeedbackResult:
        """
        1. Read bead via beads.show_bead(bead_id)
        2. Parse FractureMetadata from notes field
        3. Compare predicted vs actual file manifests
        4. Calculate accuracy
        5. Log via logger.log_feedback()
        6. Return FeedbackResult
        """
```

## Accuracy Calculation
```python
predicted = set(manifest.creates + manifest.modifies)
actual = set(actual_creates + actual_modifies)

missed = actual - predicted       # files touched but not predicted
false_preds = predicted - actual  # files predicted but not touched
correct = predicted & actual

accuracy = len(correct) / len(predicted | actual) if (predicted | actual) else 1.0
```

## Completion Criteria
- Reads bead metadata and parses FractureMetadata JSON from notes
- Computes accuracy correctly
- Logs feedback event
- Returns structured FeedbackResult

## When Done
```bash
bd close <ID> "Feedback tool complete, accuracy calculation tested"
```
Unblocks: Lane N (server exposes feedback as MCP tool)
