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
from fracture.dependency import derive_dependencies, determine_phases, validate_graph
from fracture.feedback import FeedbackProcessor
from fracture.instructor import Instructor
from fracture.logger import FractureLogger
from fracture.model import ModelClient
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
        # Step 1: Analyze task into units
        units = await analyzer.analyze(task, project, artifacts)

        # Step 2: Derive dependency edges from write-set overlap
        edges = derive_dependencies(units)

        # Step 3: Process recursion (expand compound units)
        units, edges = await recursion_engine.process(
            units, edges, project, depth=0
        )

        # Step 4: Validate graph and fix conflicts
        conflicts = validate_graph(units, edges)
        # validate_graph returns list[tuple[int, int, set[str]]] per actual signature
        validation_result: dict[str, Any] = {
            "conflicts": [
                {"unit_a": a, "unit_b": b, "shared_files": list(files)}
                for a, b, files in conflicts
            ]
        }

        # Step 5: Determine execution phases
        phases = determine_phases(units, edges)

        # Step 6: Idempotency check
        task_hash = hashlib.sha256(task.encode()).hexdigest()[:12]
        existing = await beads_client.list_open_beads(decomposition_id=task_hash)
        if existing:
            raise DecompositionError(
                f"Task already decomposed: {len(existing)} beads open (id={task_hash})"
            )

        decomposition_id = task_hash
        bead_ids: list[str] = []

        if not dry_run:
            # Step 7a: Get codebase context for planner/instructor
            context = await tc_client.get_context(task, project)

            # Step 7b: Generate plans
            plans = await planner.generate_plans(units, edges, context)

            # Step 7c: Generate CLAUDE.md instructions
            instructions = await instructor.generate_instructions(units, plans, context)

            # Build bead data list in topological order (phases already ordered)
            # Map unit index → phase number
            unit_phase: dict[int, int] = {}
            for phase in phases:
                for uid in phase.bead_ids:
                    unit_phase[int(uid)] = phase.phase_number

            # Build unit-index → dependency unit-indices map from edges
            # edges: from_unit depends on to_unit (to_unit must finish first)
            unit_deps: dict[int, list[int]] = {i: [] for i in range(len(units))}
            for edge in edges:
                unit_deps[edge.from_unit].append(edge.to_unit)

            # Create bead data in phase order
            unit_bead_id: dict[int, str] = {}
            all_bead_data: list[dict[str, Any]] = []

            # Sort units by phase so dependencies are created before dependents
            phase_order: list[int] = []
            for phase in phases:
                for uid in phase.bead_ids:
                    phase_order.append(int(uid))
            # Add any units not in phases (edge case)
            for i in range(len(units)):
                if i not in phase_order:
                    phase_order.append(i)

            for idx in phase_order:
                unit = units[idx]
                plan_md = plans[idx] if idx < len(plans) else ""
                instr_md = instructions[idx] if idx < len(instructions) else ""
                phase_num = unit_phase.get(idx, 1)

                # Find which bead IDs this unit depends on
                dep_bead_ids = [
                    unit_bead_id[dep_idx]
                    for dep_idx in unit_deps.get(idx, [])
                    if dep_idx in unit_bead_id
                ]

                # Build FractureMetadata for notes
                metadata = FractureMetadata(
                    file_manifest=unit.file_manifest,
                    phase=phase_num,
                    parallel_with=[],
                    decomposition_id=decomposition_id,
                    estimated_hours=unit.estimated_hours,
                )
                notes_data = {"fracture": asdict(metadata), "decomposition_id": decomposition_id}

                bead_data: dict[str, Any] = {
                    "title": unit.title,
                    "bead_type": "task",
                    "priority": phase_num,
                    "deps": dep_bead_ids,
                    "description": unit.description,
                    "design": plan_md,
                    "acceptance": unit.deliverable,
                    "notes": json.dumps(notes_data),
                    "_unit_idx": idx,  # internal, used for id mapping
                }
                all_bead_data.append(bead_data)

            # Prepare clean list without internal keys for create_beads_transactional
            clean_bead_data = [
                {k: v for k, v in bd.items() if not k.startswith("_")}
                for bd in all_bead_data
            ]

            # Step 7c: Create beads transactionally
            created_ids = await beads_client.create_beads_transactional(clean_bead_data)

            # Map unit index → bead_id for phase population
            for i, idx in enumerate(phase_order):
                if i < len(created_ids):
                    unit_bead_id[idx] = created_ids[i]

            bead_ids = created_ids

            # Populate phase bead_ids with actual bead IDs
            for phase in phases:
                phase.bead_ids = [
                    unit_bead_id[int(uid)]
                    for uid in phase.bead_ids
                    if int(uid) in unit_bead_id
                ]
        else:
            plans = []
            instructions = []

        # Step 8: Log decomposition
        beads_log = [
            {
                "bead_id": bead_ids[i] if i < len(bead_ids) else None,
                "title": units[i].title,
                "estimated_hours": units[i].estimated_hours,
            }
            for i in range(len(units))
        ]
        fracture_logger.log_decomposition(
            task=task,
            model_used=config.model.claude_model
            if config.model.provider == "claude"
            else config.model.local_model,
            dry_run=dry_run,
            beads=beads_log,
            phases=phases,
            tc_queries=[],
            validation=validation_result,
            recursion_events=[],
            decomposition_id=decomposition_id,
        )

        # Step 9: Return result
        return {
            "decomposition_id": decomposition_id,
            "dry_run": dry_run,
            "unit_count": len(units),
            "bead_ids": bead_ids,
            "phases": [asdict(p) for p in phases],
            "conflicts": validation_result["conflicts"],
            "units": [asdict(u) for u in units],
            "edges": [asdict(e) for e in edges],
        }

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
                description=bead.get("body", ""),
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

        # Step 2 & 3: Run the same decompose pipeline
        units = await analyzer.analyze(sub_task, project)
        edges = derive_dependencies(units)
        units, edges = await recursion_engine.process(units, edges, project, depth=0)
        conflicts = validate_graph(units, edges)
        validation_result: dict[str, Any] = {
            "conflicts": [
                {"unit_a": a, "unit_b": b, "shared_files": list(files)}
                for a, b, files in conflicts
            ]
        }
        phases = determine_phases(units, edges)

        sub_task_hash = hashlib.sha256(f"{bead_id}:{sub_task}".encode()).hexdigest()[:12]
        sub_bead_ids: list[str] = []

        if not dry_run:
            context = await tc_client.get_context(sub_task, project)
            plans = await planner.generate_plans(units, edges, context)
            instructions = await instructor.generate_instructions(units, plans, context)

            unit_phase: dict[int, int] = {}
            for phase in phases:
                for uid in phase.bead_ids:
                    unit_phase[int(uid)] = phase.phase_number

            unit_deps: dict[int, list[int]] = {i: [] for i in range(len(units))}
            for edge in edges:
                unit_deps[edge.from_unit].append(edge.to_unit)

            unit_bead_id: dict[int, str] = {}
            phase_order: list[int] = []
            for phase in phases:
                for uid in phase.bead_ids:
                    phase_order.append(int(uid))
            for i in range(len(units)):
                if i not in phase_order:
                    phase_order.append(i)

            all_bead_data: list[dict[str, Any]] = []
            for idx in phase_order:
                unit = units[idx]
                plan_md = plans[idx] if idx < len(plans) else ""
                phase_num = unit_phase.get(idx, 1)

                dep_bead_ids = [
                    unit_bead_id[dep_idx]
                    for dep_idx in unit_deps.get(idx, [])
                    if dep_idx in unit_bead_id
                ]

                metadata = FractureMetadata(
                    file_manifest=unit.file_manifest,
                    phase=phase_num,
                    parallel_with=[],
                    decomposition_id=sub_task_hash,
                    estimated_hours=unit.estimated_hours,
                )
                notes_data = {
                    "fracture": asdict(metadata),
                    "decomposition_id": sub_task_hash,
                    "parent_bead_id": bead_id,
                }

                all_bead_data.append({
                    "title": unit.title,
                    "bead_type": "task",
                    "priority": phase_num,
                    "deps": dep_bead_ids,
                    "description": unit.description,
                    "design": plan_md,
                    "acceptance": unit.deliverable,
                    "notes": json.dumps(notes_data),
                    "_unit_idx": idx,
                })

            clean_bead_data = [
                {k: v for k, v in bd.items() if not k.startswith("_")}
                for bd in all_bead_data
            ]

            sub_bead_ids = await beads_client.create_beads_transactional(clean_bead_data)

            for i, idx in enumerate(phase_order):
                if i < len(sub_bead_ids):
                    unit_bead_id[idx] = sub_bead_ids[i]

            # Step 4b: Close the original bead
            await beads_client.close_bead(
                bead_id, f"decomposed into sub-beads: {', '.join(sub_bead_ids)}"
            )

            for phase in phases:
                phase.bead_ids = [
                    unit_bead_id[int(uid)]
                    for uid in phase.bead_ids
                    if int(uid) in unit_bead_id
                ]
        else:
            plans = []

        beads_log = [
            {
                "bead_id": sub_bead_ids[i] if i < len(sub_bead_ids) else None,
                "title": units[i].title,
                "estimated_hours": units[i].estimated_hours,
            }
            for i in range(len(units))
        ]
        fracture_logger.log_decomposition(
            task=sub_task,
            model_used=config.model.claude_model
            if config.model.provider == "claude"
            else config.model.local_model,
            dry_run=dry_run,
            beads=beads_log,
            phases=phases,
            tc_queries=[],
            validation=validation_result,
            recursion_events=[],
            decomposition_id=sub_task_hash,
        )

        return {
            "parent_bead_id": bead_id,
            "decomposition_id": sub_task_hash,
            "dry_run": dry_run,
            "sub_bead_ids": sub_bead_ids,
            "unit_count": len(units),
            "phases": [asdict(p) for p in phases],
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
