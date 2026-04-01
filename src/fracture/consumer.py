"""consumer.py — Redis Stream consumer for Fracture.

Reads approved tasks from Breakdown's stream:breakdown-approved and runs
the decompose pipeline for each message.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import socket
from typing import Any

import redis.asyncio as aioredis

from fracture.analyzer import Analyzer
from fracture.beads import BeadsClient
from fracture.config import load_config
from fracture.instructor import Instructor
from fracture.logger import FractureLogger
from fracture.model import ModelClient
from fracture.pipeline import run_decompose_pipeline
from fracture.planner import Planner
from fracture.recursion import RecursionEngine
from fracture.tersecontext import TerseContextClient
from fracture.types import RedisConfig

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
            logger.warning("Could not parse research field as JSON")
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
        try:
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

            while self._running:
                results = await r.xreadgroup(
                    rc.consumer_group,
                    consumer_name,
                    {rc.input_stream: ">"},
                    count=1,
                    block=min(rc.block_ms, 1000),  # cap at 1s for responsive shutdown
                )
                if not results:
                    continue

                for _stream, messages in results:
                    for msg_id, fields in messages:
                        await self._handle(
                            msg_id, fields, r, rc,
                            analyzer, planner, instructor,
                            recursion_engine, beads_client, fracture_logger,
                            tc_client, config,
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
        tc_client: TerseContextClient,
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

        # Fix 2: Validate required fields before running pipeline
        if not task or not project:
            logger.error(
                "Message %s missing required fields (task=%r, project=%r) — skipping",
                msg_id, task, project,
            )
            if rc.output_stream:
                try:
                    await r.xadd(rc.output_stream, {
                        "task_id": task_id,
                        "status": "error",
                        "error": "missing required fields: description or repo",
                    })
                except Exception as exc:
                    logger.warning("Failed to write to output stream: %s", exc)
            await r.xack(rc.input_stream, rc.consumer_group, msg_id)
            return

        logger.info("Processing task %s: %.60s...", task_id, task)

        try:
            result = await run_decompose_pipeline(
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
            )
            logger.info(
                "Task %s decomposed: %d beads, %d phases",
                task_id, result["unit_count"], len(result["phases"]),
            )

            if rc.output_stream:
                try:
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
                    logger.warning("Failed to write to output stream: %s", exc)

        except Exception as exc:
            logger.error("Failed to decompose task %s: %s", task_id, exc, exc_info=True)
            if rc.output_stream:
                try:
                    await r.xadd(rc.output_stream, {
                        "task_id": task_id,
                        "status": "error",
                        "error": str(exc),
                    })
                except Exception as write_exc:
                    logger.warning("Failed to write error to output stream: %s", write_exc)
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

    parser = argparse.ArgumentParser(description="Fracture Redis Stream consumer")
    parser.add_argument("--config", default="fracture.yaml", help="Path to fracture.yaml")
    args = parser.parse_args()

    consumer = FractureConsumer(config_path=args.config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, consumer.stop)

    await consumer.run()


if __name__ == "__main__":
    asyncio.run(main())
