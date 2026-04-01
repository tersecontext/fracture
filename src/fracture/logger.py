"""logger.py — Append-only JSONL audit log writer for Fracture.

Logs decomposition events, feedback, and errors to .fracture/logs/.
Each log file is named YYYY-MM-DD-{decomposition_id}.jsonl and contains
one JSON object per line.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from fracture.types import FeedbackResult, Phase


def _now_iso() -> str:
    """Return current UTC time as an ISO8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    """Return today's date as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class FractureLogger:
    def __init__(self, log_dir: str, project_dir: str) -> None:
        """Initialize. Creates log_dir if it doesn't exist.

        log_dir may be relative to project_dir.
        """
        if os.path.isabs(log_dir):
            self._log_dir = log_dir
        else:
            self._log_dir = os.path.join(project_dir, log_dir)
        os.makedirs(self._log_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_decomposition(
        self,
        task: str,
        model_used: str,
        dry_run: bool,
        beads: list[dict],
        phases: list[Phase],
        tc_queries: list[dict],
        validation: dict,
        recursion_events: list[dict],
        decomposition_id: str,
    ) -> str:
        """Write a decomposition event to the log. Returns log file path."""
        phases_serialized = [
            asdict(p) if isinstance(p, Phase) else p for p in phases
        ]
        entry = {
            "type": "decomposition",
            "timestamp": _now_iso(),
            "task": task,
            "model": model_used,
            "dry_run": dry_run,
            "tersecontext_queries": tc_queries,
            "beads": beads,
            "phases": phases_serialized,
            "recursion_events": recursion_events,
            "validation": validation,
            "decomposition_id": decomposition_id,
        }
        log_path = self.get_log_path(decomposition_id)
        self._append(log_path, entry)
        return log_path

    def log_feedback(self, feedback: FeedbackResult) -> None:
        """Append a feedback event to the log."""
        entry = {
            "type": "feedback",
            "timestamp": _now_iso(),
            "bead_id": feedback.bead_id,
            "predicted_creates": feedback.predicted_creates,
            "predicted_modifies": feedback.predicted_modifies,
            "actual_creates": feedback.actual_creates,
            "actual_modifies": feedback.actual_modifies,
            "missed_files": feedback.missed_files,
            "false_predictions": feedback.false_predictions,
            "accuracy": feedback.accuracy,
        }
        # Feedback is appended to the most recent log or a standalone file.
        # Use bead_id as the decomposition_id component for the path.
        log_path = self.get_log_path(feedback.bead_id)
        self._append(log_path, entry)

    def log_error(
        self,
        decomposition_id: str,
        error: str,
        partial_beads: list[str],
    ) -> None:
        """Log a failed decomposition with partial state."""
        entry = {
            "type": "error",
            "timestamp": _now_iso(),
            "decomposition_id": decomposition_id,
            "error": error,
            "partial_beads": partial_beads,
        }
        log_path = self.get_log_path(decomposition_id)
        self._append(log_path, entry)

    def get_log_path(self, decomposition_id: str) -> str:
        """Return the log file path for a given decomposition."""
        filename = f"{_today()}-{decomposition_id}.jsonl"
        return os.path.join(self._log_dir, filename)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, path: str, entry: dict) -> None:
        """Append a single JSON object as one line to the log file."""
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
