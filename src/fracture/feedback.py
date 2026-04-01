"""feedback.py — Post-execution accuracy reporting for Fracture.

Compares predicted file manifests against actual files changed after bead
execution, calculates accuracy, and logs results via FractureLogger.
"""

from __future__ import annotations

import json

from fracture.beads import BeadsClient
from fracture.logger import FractureLogger
from fracture.types import FeedbackResult, FileManifest, FractureMetadata


class FeedbackProcessor:
    """Compares predicted vs actual file changes and logs accuracy."""

    def __init__(self, beads: BeadsClient, logger: FractureLogger) -> None:
        """Initialise with a BeadsClient and FractureLogger.

        Args:
            beads:  Client used to retrieve bead details (read-only usage here).
            logger: Audit log writer where feedback events are appended.
        """
        self._beads = beads
        self._logger = logger

    async def process_feedback(
        self,
        bead_id: str,
        actual_creates: list[str],
        actual_modifies: list[str],
    ) -> FeedbackResult:
        """Compare predicted file manifest against actual changes and log accuracy.

        Steps:
        1. Read the bead via BeadsClient.show_bead().
        2. Parse FractureMetadata from the notes field (JSON string).
        3. Compare predicted vs actual file manifests.
        4. Calculate accuracy as Jaccard similarity over the union of files.
        5. Log via FractureLogger.log_feedback().
        6. Return a FeedbackResult.

        If the notes field is empty or missing the "fracture" key, an empty
        manifest (no predicted files) is assumed.

        Args:
            bead_id:         The bead ID to evaluate.
            actual_creates:  Files actually created during execution.
            actual_modifies: Files actually modified during execution.

        Returns:
            A populated FeedbackResult with accuracy and diff sets.
        """
        bead_data = await self._beads.show_bead(bead_id)

        # --- Parse FractureMetadata from notes ----------------------------
        manifest = FileManifest(creates=[], modifies=[], reads=[])
        raw_notes = bead_data.get("notes", "") or ""
        if raw_notes:
            try:
                notes_obj = json.loads(raw_notes)
                fracture_block = notes_obj.get("fracture")
                if fracture_block is not None:
                    metadata = FractureMetadata.from_json(fracture_block)
                    manifest = metadata.file_manifest
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                # Malformed notes — fall through to empty manifest.
                pass

        # --- Calculate accuracy -------------------------------------------
        predicted: set[str] = set(manifest.creates) | set(manifest.modifies)
        actual: set[str] = set(actual_creates) | set(actual_modifies)

        missed = sorted(actual - predicted)          # touched but not predicted
        false_preds = sorted(predicted - actual)     # predicted but not touched
        correct = predicted & actual

        union = predicted | actual
        accuracy = len(correct) / len(union) if union else 1.0

        # --- Build result -------------------------------------------------
        result = FeedbackResult(
            bead_id=bead_id,
            predicted_creates=list(manifest.creates),
            predicted_modifies=list(manifest.modifies),
            actual_creates=list(actual_creates),
            actual_modifies=list(actual_modifies),
            missed_files=missed,
            false_predictions=false_preds,
            accuracy=accuracy,
        )

        # --- Log ----------------------------------------------------------
        self._logger.log_feedback(result)

        return result
