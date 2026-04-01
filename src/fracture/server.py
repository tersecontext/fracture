"""server.py — MCP server for Fracture.

Exposes four tools: decompose, validate, further_decompose, feedback.
Wires together all Fracture modules into a FastMCP server with stdio transport.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP  # type: ignore[no-reattr]

from fracture.analyzer import Analyzer
from fracture.beads import BeadsClient
from fracture.config import load_config
from fracture.dependency import validate_graph
from fracture.feedback import FeedbackProcessor
from fracture.instructor import Instructor
from fracture.logger import FractureLogger
from fracture.model import ModelClient
from fracture.pipeline import run_decompose_pipeline
from fracture.planner import Planner
from fracture.recursion import RecursionEngine
from fracture.tersecontext import TerseContextClient
from fracture.types import (
    FractureMetadata,
    Unit,
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DecompositionError(Exception):
    """Raised when decomposition cannot proceed (e.g. duplicate task)."""


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(config_path: str = "fracture.yaml") -> FastMCP:
    """Build the full dependency graph of internal objects and register tools.

    Args:
        config_path: Path to the fracture.yaml config file.

    Returns:
        A configured FastMCP server instance ready to run.
    """
    config = load_config(config_path)

    tc_client = TerseContextClient(config.tersecontext_endpoint)
    model = ModelClient(config.model)
    analyzer = Analyzer(tc_client, model, config)
    planner = Planner(model)
    instructor = Instructor(model)
    recursion_engine = RecursionEngine(analyzer, config)
    beads_client = BeadsClient(config.project_dir)
    fracture_logger = FractureLogger(config.log_dir, config.project_dir)
    feedback_proc = FeedbackProcessor(beads_client, fracture_logger)

    mcp = FastMCP("fracture")

    # -----------------------------------------------------------------------
    # Tool: decompose
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def decompose(
        task: str,
        project: str,
        dry_run: bool = False,
        artifacts: list[dict] | None = None,
        max_bead_hours: float = 3,
        max_parallel_lanes: int = 4,
        max_recursion_depth: int = 4,
    ) -> dict:
        """Decompose a task into dependency-ordered beads.

        Runs the full analysis, planning, and bead-creation pipeline.

        Args:
            task:                 Natural language description of the work.
            project:              Project identifier for TerseContext queries.
            dry_run:              If True, skip bead creation (plan only).
            artifacts:            Optional list of artifact dicts passed to analyzer.
            max_bead_hours:       Maximum estimated hours per bead.
            max_parallel_lanes:   Maximum parallel execution lanes.
            max_recursion_depth:  Maximum recursion depth for compound tasks.

        Returns:
            Dict with decomposition result including units, edges, phases,
            bead_ids (empty on dry_run), and decomposition_id.
        """
        try:
            return await run_decompose_pipeline(
                task=task,
                project=project,
                artifacts=artifacts,
                analyzer=analyzer,
                planner=planner,
                instructor=instructor,
                recursion_engine=recursion_engine,
                beads_client=beads_client,
                fracture_logger=fracture_logger,
                tc_client=tc_client,
                config=config,
                dry_run=dry_run,
            )
        except ValueError as exc:
            raise DecompositionError(str(exc)) from exc

    # -----------------------------------------------------------------------
    # Tool: validate
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def validate(bead_ids: list[str]) -> dict:
        """Validate dependency ordering for a set of beads.

        Fetches each bead, parses its FractureMetadata, and checks for
        write-set conflicts that lack a dependency edge.

        Args:
            bead_ids: List of bead IDs to validate.

        Returns:
            Dict with conflicts and suggested dependency edges.
        """
        units: list[Unit] = []
        bead_id_map: dict[int, str] = {}

        for bead_id in bead_ids:
            bead = await beads_client.show_bead(bead_id)
            raw_notes = bead.get("notes", "") or ""
            try:
                notes_data = json.loads(raw_notes)
                fracture_data = notes_data.get("fracture", {})
                metadata = FractureMetadata.from_json(fracture_data)
                file_manifest = metadata.file_manifest
            except (json.JSONDecodeError, KeyError, TypeError):
                from fracture.types import FileManifest
                file_manifest = FileManifest(creates=[], modifies=[], reads=[])

            unit = Unit(
                title=bead.get("title", bead_id),
                description=bead.get("body") or bead.get("description") or "",
                deliverable="",
                file_manifest=file_manifest,
                estimated_hours=0.0,
                rationale="",
            )
            idx = len(units)
            units.append(unit)
            bead_id_map[idx] = bead_id

        # No prior edges — validate from scratch
        conflicts = validate_graph(units, [])
        suggested_edges = [
            {
                "from_bead": bead_id_map.get(a, str(a)),
                "to_bead": bead_id_map.get(b, str(b)),
                "shared_files": list(files),
                "reason": "write-set overlap requires dependency",
            }
            for a, b, files in conflicts
        ]

        return {
            "valid": len(conflicts) == 0,
            "conflicts": [
                {
                    "bead_a": bead_id_map.get(a, str(a)),
                    "bead_b": bead_id_map.get(b, str(b)),
                    "shared_files": list(files),
                }
                for a, b, files in conflicts
            ],
            "suggested_edges": suggested_edges,
        }

    # -----------------------------------------------------------------------
    # Tool: further_decompose
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def further_decompose(
        bead_id: str,
        project: str,
        dry_run: bool = False,
    ) -> dict:
        """Decompose an existing bead into sub-beads.

        Retrieves the bead, uses its description as the sub-task, runs the
        decompose pipeline, closes the original bead, and creates sub-beads.

        Args:
            bead_id:  The bead ID to decompose further.
            project:  Project identifier for TerseContext queries.
            dry_run:  If True, skip bead creation and closing.

        Returns:
            Dict with sub-bead IDs and decomposition details.
        """
        # Step 1: Get the original bead
        bead = await beads_client.show_bead(bead_id)
        sub_task = bead.get("body") or bead.get("description") or bead.get("title", "")

        try:
            result = await run_decompose_pipeline(
                task=sub_task,
                project=project,
                artifacts=None,
                analyzer=analyzer,
                planner=planner,
                instructor=instructor,
                recursion_engine=recursion_engine,
                beads_client=beads_client,
                fracture_logger=fracture_logger,
                tc_client=tc_client,
                config=config,
                dry_run=dry_run,
            )
        except ValueError as exc:
            raise DecompositionError(str(exc)) from exc

        sub_bead_ids = result["bead_ids"]

        if not dry_run and sub_bead_ids:
            # Close the original bead now that sub-beads have been created
            await beads_client.close_bead(
                bead_id, f"decomposed into sub-beads: {', '.join(sub_bead_ids)}"
            )

        return {
            "parent_bead_id": bead_id,
            "decomposition_id": result["decomposition_id"],
            "dry_run": dry_run,
            "sub_bead_ids": sub_bead_ids,
            "unit_count": result["unit_count"],
            "phases": result["phases"],
            "conflicts": result["conflicts"],
        }

    # -----------------------------------------------------------------------
    # Tool: feedback
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def feedback(
        bead_id: str,
        actual_creates: list[str],
        actual_modifies: list[str],
    ) -> dict:
        """Report actual file changes for accuracy tracking.

        Compares the predicted file manifest against actual changes made
        during bead execution and returns an accuracy report.

        Args:
            bead_id:          The bead ID that was executed.
            actual_creates:   Files actually created during execution.
            actual_modifies:  Files actually modified during execution.

        Returns:
            Accuracy report as a dict.
        """
        result = await feedback_proc.process_feedback(
            bead_id=bead_id,
            actual_creates=actual_creates,
            actual_modifies=actual_modifies,
        )
        return asdict(result)

    return mcp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server = create_server()
    server.run()  # stdio transport by default
