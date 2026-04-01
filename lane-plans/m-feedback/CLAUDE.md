# CLAUDE.md — Lane M: Feedback Tool

## Your Task
Create `src/fracture/feedback.py`. Compares predicted vs actual file changes after bead execution. Read PLAN.md.

## Rules
- Import BeadsClient from fracture.beads, FractureLogger from fracture.logger
- Parse FractureMetadata JSON from the bead's notes field
- Accuracy = |correct| / |predicted ∪ actual|

## Do NOT
- Modify beads — feedback is passive reporting only
- Call LLMs
