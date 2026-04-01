"""pipeline.py — Shared bead-creation logic for the decompose pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from dataclasses import asdict
from typing import Any

from fracture.beads import BeadsClient
from fracture.dependency import derive_dependencies, determine_phases, validate_graph
from fracture.instructor import Instructor
from fracture.logger import FractureLogger
from fracture.planner import Planner
from fracture.recursion import RecursionEngine
from fracture.tersecontext import TerseContextClient
from fracture.types import (
    FractureMetadata,
)

logger = logging.getLogger(__name__)


async def run_decompose_pipeline(
    *,
    task: str,
    project: str,
    artifacts: list[dict] | None,
    analyzer,           # Analyzer — avoid circular import
    planner: Planner,
    instructor: Instructor,
    recursion_engine: RecursionEngine,
    beads_client: BeadsClient,
    fracture_logger: FractureLogger,
    tc_client: TerseContextClient,
    config: Any,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the full decompose pipeline and return a result dict.

    Steps:
        1. analyzer.analyze → units
        2. derive_dependencies → edges
        3. recursion_engine.process → flat units, edges
        4. validate_graph → conflicts
        5. determine_phases → phases
        6. Idempotency check (skipped on dry_run)
        7. If not dry_run: planner → instructor → create_beads_transactional
        8. log_decomposition
        9. Return result dict

    Returns:
        dict with keys: decomposition_id, dry_run, unit_count, bead_ids,
                        phases, conflicts, units, edges
    """
    # Step 1: Analyze task into units
    units = await analyzer.analyze(task, project, artifacts)
    if not units:
        raise ValueError("Analyzer returned no units for the given task.")

    # Step 2: Derive dependency edges from write-set overlap
    edges = derive_dependencies(units)

    # Step 3: Process recursion (expand compound units)
    units, edges = await recursion_engine.process(units, edges, project, depth=0)

    # Step 4: Validate graph
    conflicts_raw = validate_graph(units, edges)
    validation_result: dict[str, Any] = {
        "conflicts": [
            {"unit_a": a, "unit_b": b, "shared_files": list(files)}
            for a, b, files in conflicts_raw
        ]
    }

    # Step 5: Determine execution phases
    phases = determine_phases(units, edges)
    task_hash = hashlib.sha256(task.encode()).hexdigest()[:12]
    decomposition_id = task_hash

    # Step 6: Idempotency check (skipped on dry_run)
    if not dry_run:
        existing = await beads_client.list_open_beads(decomposition_id=task_hash)
        if existing:
            raise ValueError(
                f"Task already decomposed: {len(existing)} beads open (id={task_hash})"
            )

    bead_ids: list[str] = []

    if not dry_run:
        # Step 7a: Get codebase context
        context = await tc_client.get_context(task, project)

        # Step 7b: Generate plans
        plans = await planner.generate_plans(units, edges, context)

        # Step 7c: Generate CLAUDE.md instructions
        instructions = await instructor.generate_instructions(units, plans, context)

        # Build unit index → phase number map
        unit_phase: dict[int, int] = {}
        for phase in phases:
            for uid in phase.bead_ids:
                unit_phase[int(uid)] = phase.phase_number

        # Build unit index → dependency unit indices map
        # edges: from_unit depends on to_unit (to_unit must finish first)
        unit_deps: dict[int, list[int]] = {i: [] for i in range(len(units))}
        for edge in edges:
            unit_deps[edge.from_unit].append(edge.to_unit)

        # Sort units by phase so dependencies are created before dependents
        phase_order: list[int] = []
        for phase in phases:
            for uid in phase.bead_ids:
                phase_order.append(int(uid))
        # Add any units not in phases (edge case)
        phased = set(phase_order)
        for i in range(len(units)):
            if i not in phased:
                phase_order.append(i)

        # Build bead data in phase order, wiring deps to already-seen bead IDs.
        # unit_bead_id is populated incrementally so dependencies that appear
        # earlier in phase_order are resolvable.
        unit_bead_id: dict[int, str] = {}
        all_bead_data: list[dict[str, Any]] = []

        for idx in phase_order:
            unit = units[idx]
            plan_md = plans[idx] if idx < len(plans) else ""
            instr_md = instructions[idx] if idx < len(instructions) else ""
            phase_num = unit_phase.get(idx, 1)

            # Resolve dependency bead IDs from units built earlier in this loop
            dep_bead_ids: list[str] = []
            for dep_idx in unit_deps.get(idx, []):
                if dep_idx in unit_bead_id:
                    dep_bead_ids.append(unit_bead_id[dep_idx])
                else:
                    logger.warning(
                        "dependency unit %d not yet created when building bead for unit %d"
                        " — dependency link dropped",
                        dep_idx,
                        idx,
                    )

            metadata = FractureMetadata(
                file_manifest=unit.file_manifest,
                phase=phase_num,
                parallel_with=[],  # parallel_with requires a second pass after bead IDs are known
                decomposition_id=decomposition_id,
                estimated_hours=unit.estimated_hours,
            )
            notes_data = {"fracture": asdict(metadata), "decomposition_id": decomposition_id}

            all_bead_data.append({
                "title": unit.title,
                "bead_type": "task",
                "priority": phase_num,
                "deps": dep_bead_ids,
                "description": unit.description,
                "design": plan_md,
                "acceptance": instr_md,
                "notes": json.dumps(notes_data),
                "_unit_idx": idx,  # internal key for id mapping; stripped before creation
            })

        # Strip internal keys before passing to BeadsClient
        clean_bead_data = [
            {k: v for k, v in bd.items() if not k.startswith("_")}
            for bd in all_bead_data
        ]

        # Step 7d: Create beads transactionally
        created_ids = await beads_client.create_beads_transactional(clean_bead_data)

        # Map unit index → bead_id
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
    model_name = (
        config.model.claude_model
        if config.model.provider == "claude"
        else config.model.local_model
    )

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
        model_used=model_name,
        dry_run=dry_run,
        beads=beads_log,
        phases=phases,
        tc_queries=[],
        validation=validation_result,
        recursion_events=[],
        decomposition_id=decomposition_id,
    )

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
