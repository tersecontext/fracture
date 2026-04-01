"""consumer.py — Redis Stream consumer for Fracture.

Reads approved tasks from Breakdown's stream:breakdown-approved and runs
the decompose pipeline for each message.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import signal
import socket
from dataclasses import asdict
from typing import Any

import redis.asyncio as aioredis

from fracture.analyzer import Analyzer
from fracture.beads import BeadsClient
from fracture.config import load_config
from fracture.dependency import derive_dependencies, determine_phases, validate_graph
from fracture.instructor import Instructor
from fracture.logger import FractureLogger
from fracture.model import ModelClient
from fracture.planner import Planner
from fracture.recursion import RecursionEngine
from fracture.tersecontext import TerseContextClient
from fracture.types import FractureMetadata, RedisConfig

logger = logging.getLogger(__name__)

COMPLEX_FIELDS = {"research", "additional_context", "optional_answers"}


# ---------------------------------------------------------------------------
# Message decoding helpers
# ---------------------------------------------------------------------------


def _decode_message(fields: dict[bytes, bytes]) -> dict[str, Any]:
    """Decode raw Redis stream fields into a usable dict.

    Handles both bytes keys/values (raw Redis protocol) and str keys/values.
    Fields listed in COMPLEX_FIELDS are JSON-parsed automatically.
    """
    decoded: dict[str, Any] = {}
    for k, v in fields.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        if key in COMPLEX_FIELDS:
            try:
                decoded[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                decoded[key] = val
        else:
            decoded[key] = val
    return decoded


def _build_artifacts(research: dict | str) -> list[dict]:
    """Extract affected_code from research as artifacts for the analyzer."""
    if isinstance(research, str):
        try:
            research = json.loads(research)
        except (json.JSONDecodeError, TypeError):
            return []
    affected = research.get("affected_code", []) if isinstance(research, dict) else []
    return [
        {
            "path": item.get("file", ""),
            "change_type": item.get("change_type", "modify"),
            "description": item.get("description", ""),
        }
        for item in affected
        if item.get("file")
    ]


# ---------------------------------------------------------------------------
# Core decompose pipeline (mirrors server.py decompose tool, without MCP layer)
# ---------------------------------------------------------------------------


async def _run_decompose(
    task: str,
    project: str,
    artifacts: list[dict] | None,
    analyzer: Analyzer,
    planner: Planner,
    instructor: Instructor,
    recursion_engine: RecursionEngine,
    beads_client: BeadsClient,
    fracture_logger: FractureLogger,
    config: Any,
) -> dict:
    """Run the full Fracture decompose pipeline and return a result dict.

    Mirrors the non-dry_run path of server.py's decompose tool as closely as
    possible, including phase-ordered bead creation and dependency wiring.
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

    # Step 6: Idempotency check
    task_hash = hashlib.sha256(task.encode()).hexdigest()[:12]
    existing = await beads_client.list_open_beads(decomposition_id=task_hash)
    if existing:
        raise ValueError(
            f"Task already decomposed: {len(existing)} beads open (id={task_hash})"
        )

    decomposition_id = task_hash

    # Step 7a: Get codebase context
    # Reuse the TerseContext client already wired into the analyzer if available;
    # fall back to building a new one from config.
    try:
        tc_client: TerseContextClient = analyzer._tc_client  # type: ignore[attr-defined]
    except AttributeError:
        tc_client = TerseContextClient(config.tersecontext_endpoint)

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
    for i in range(len(units)):
        if i not in phase_order:
            phase_order.append(i)

    # Build bead data in phase order, wiring deps to already-created bead IDs.
    # This mirrors server.py exactly: unit_bead_id is populated incrementally,
    # so dependencies that appear earlier in phase_order are resolvable.
    unit_bead_id: dict[int, str] = {}
    all_bead_data: list[dict[str, Any]] = []

    for idx in phase_order:
        unit = units[idx]
        plan_md = plans[idx] if idx < len(plans) else ""
        instr_md = instructions[idx] if idx < len(instructions) else ""
        phase_num = unit_phase.get(idx, 1)

        # Resolve dependency bead IDs from units created earlier in this loop
        dep_bead_ids: list[str] = []
        for dep_idx in unit_deps.get(idx, []):
            if dep_idx in unit_bead_id:
                dep_bead_ids.append(unit_bead_id[dep_idx])
            else:
                # This case arises when a dependency unit appears later in
                # phase_order than the dependent, which should not happen if phases
                # are computed correctly.
                logger.warning(
                    "dependency unit %d not yet created when building bead for unit %d"
                    " — dependency link dropped",
                    dep_idx,
                    idx,
                )

        metadata = FractureMetadata(
            file_manifest=unit.file_manifest,
            phase=phase_num,
            parallel_with=[],  # parallel_with requires a second pass after bead IDs are known; not yet implemented
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

    # Map unit index → bead_id (needed for phase population)
    for i, idx in enumerate(phase_order):
        if i < len(created_ids):
            unit_bead_id[idx] = created_ids[i]

    bead_ids = created_ids

    # Populate phase bead_ids with actual bead IDs (mirrors server.py)
    for phase in phases:
        phase.bead_ids = [
            unit_bead_id[int(uid)]
            for uid in phase.bead_ids
            if int(uid) in unit_bead_id
        ]

    # Step 8: Log decomposition
    beads_log = [
        {
            "bead_id": bead_ids[i] if i < len(bead_ids) else None,
            "title": units[i].title,
            "estimated_hours": units[i].estimated_hours,
        }
        for i in range(len(units))
    ]
    model_name = (
        config.model.claude_model
        if config.model.provider == "claude"
        else config.model.local_model
    )
    fracture_logger.log_decomposition(
        task=task,
        model_used=model_name,
        dry_run=False,
        beads=beads_log,
        phases=phases,
        tc_queries=[],
        validation=validation_result,
        recursion_events=[],
        decomposition_id=decomposition_id,
    )

    return {
        "decomposition_id": decomposition_id,
        "unit_count": len(units),
        "bead_ids": bead_ids,
        "phases": [asdict(p) for p in phases],
        "conflicts": validation_result["conflicts"],
    }


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class FractureConsumer:
    """Async Redis Stream consumer that drives the Fracture decompose pipeline."""

    def __init__(self, config_path: str = "fracture.yaml") -> None:
        self._config_path = config_path
        self._running = False

    async def run(self) -> None:
        """Connect to Redis, join the consumer group, and process messages."""
        config = load_config(self._config_path)
        if config.redis is None:
            raise RuntimeError("No [redis] section in fracture.yaml")

        rc: RedisConfig = config.redis
        consumer_name = rc.consumer_name or socket.gethostname()

        # Build pipeline components
        tc_client = TerseContextClient(config.tersecontext_endpoint)
        model = ModelClient(config.model)
        analyzer = Analyzer(tc_client, model, config)
        planner = Planner(model)
        instructor = Instructor(model)
        recursion_engine = RecursionEngine(analyzer, config)
        beads_client = BeadsClient(config.project_dir)
        fracture_logger = FractureLogger(config.log_dir, config.project_dir)

        r = aioredis.from_url(rc.url)

        # Ensure consumer group exists
        try:
            await r.xgroup_create(rc.input_stream, rc.consumer_group, id="0", mkstream=True)
            logger.info("Created consumer group %s on %s", rc.consumer_group, rc.input_stream)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
            logger.info("Consumer group %s already exists", rc.consumer_group)

        self._running = True
        logger.info("Fracture consumer started — listening on %s", rc.input_stream)

        try:
            while self._running:
                results = await r.xreadgroup(
                    rc.consumer_group,
                    consumer_name,
                    {rc.input_stream: ">"},
                    count=1,
                    block=rc.block_ms,
                )
                if not results:
                    continue

                for _stream, messages in results:
                    for msg_id, fields in messages:
                        await self._handle(
                            msg_id, fields, r, rc,
                            analyzer, planner, instructor,
                            recursion_engine, beads_client, fracture_logger, config,
                        )
        finally:
            await r.aclose()
            logger.info("Fracture consumer stopped")

    async def _handle(
        self,
        msg_id: bytes,
        fields: dict,
        r: aioredis.Redis,
        rc: RedisConfig,
        analyzer: Analyzer,
        planner: Planner,
        instructor: Instructor,
        recursion_engine: RecursionEngine,
        beads_client: BeadsClient,
        fracture_logger: FractureLogger,
        config: Any,
    ) -> None:
        """Process a single stream message end-to-end.

        Always acknowledges the message — errors are reported via the output
        stream rather than being retried, to avoid poison-pill loops.
        """
        msg = _decode_message(fields)
        task_id = msg.get("task_id", "unknown")
        task = msg.get("description", "")
        project = msg.get("repo", "")
        artifacts = _build_artifacts(msg.get("research", {}))

        logger.info("Processing task %s: %.60s...", task_id, task)

        try:
            result = await _run_decompose(
                task=task,
                project=project,
                artifacts=artifacts,
                analyzer=analyzer,
                planner=planner,
                instructor=instructor,
                recursion_engine=recursion_engine,
                beads_client=beads_client,
                fracture_logger=fracture_logger,
                config=config,
            )
            logger.info(
                "Task %s decomposed: %d beads, %d phases",
                task_id, result["unit_count"], len(result["phases"]),
            )

            if rc.output_stream:
                await r.xadd(rc.output_stream, {
                    "task_id": task_id,
                    "decomposition_id": result["decomposition_id"],
                    "bead_ids": json.dumps(result["bead_ids"]),
                    "unit_count": str(result["unit_count"]),
                    "phases": json.dumps(result["phases"]),
                    "conflicts": json.dumps(result["conflicts"]),
                    "status": "ok",
                })

        except Exception as exc:
            logger.error("Failed to decompose task %s: %s", task_id, exc, exc_info=True)
            if rc.output_stream:
                await r.xadd(rc.output_stream, {
                    "task_id": task_id,
                    "status": "error",
                    "error": str(exc),
                })
        finally:
            # Always ack — failed messages are reported via output stream, not retried
            await r.xack(rc.input_stream, rc.consumer_group, msg_id)

    def stop(self) -> None:
        """Signal the consumer loop to exit cleanly."""
        self._running = False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    consumer = FractureConsumer()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, consumer.stop)

    await consumer.run()


if __name__ == "__main__":
    asyncio.run(main())
