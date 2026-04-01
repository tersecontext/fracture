"""planner.py — LLM Call 2 (PLAN) orchestration for Fracture.

Takes analyzed units, dependency graph, and TerseContext codebase context,
calls the model, and returns plan_md content per unit.
"""

from __future__ import annotations

import warnings

from fracture.model import ModelClient
from fracture.prompts import build_plan_prompt
from fracture.types import CodebaseContext, DependencyEdge, Unit

_MAX_PLAN_LINES = 150


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PlanningError(Exception):
    """Raised when plan generation fails or produces invalid output."""


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class Planner:
    """Orchestrates LLM Call 2: PLAN."""

    def __init__(self, model: ModelClient) -> None:
        self._model = model

    async def generate_plans(
        self,
        units: list[Unit],
        edges: list[DependencyEdge],
        context: CodebaseContext,
    ) -> list[str]:
        """Generate plan_md strings for each unit.

        Returns a list of plan_md strings, one per unit, in unit order.

        Raises:
            PlanningError: if the model response is missing plans for any unit,
                           or if the response cannot be parsed.
        """
        if not units:
            return []

        system_prompt, user_message = build_plan_prompt(units, edges, context)

        try:
            response = await self._model.call_json(system_prompt, user_message)
        except Exception as exc:
            raise PlanningError(f"Model call failed during planning: {exc}") from exc

        raw_plans = response.get("plans")
        if not isinstance(raw_plans, list):
            raise PlanningError(
                f"Expected 'plans' list in model response, got: {type(raw_plans)}"
            )

        # Index plans by unit_index
        plans_by_index: dict[int, str] = {}
        for entry in raw_plans:
            if not isinstance(entry, dict):
                raise PlanningError(f"Plan entry is not a dict: {entry!r}")
            unit_index = entry.get("unit_index")
            plan_md = entry.get("plan_md", "")
            if unit_index is None:
                raise PlanningError(f"Plan entry missing 'unit_index': {entry!r}")
            plans_by_index[int(unit_index)] = plan_md

        # Validate: one plan per unit
        missing = [i for i in range(len(units)) if i not in plans_by_index]
        if missing:
            raise PlanningError(
                f"Missing plans for unit indices: {missing}"
            )

        # Build result list in unit order, applying per-plan validation
        result: list[str] = []
        for i, unit in enumerate(units):
            plan_md = plans_by_index[i]

            # Validate: plan under 150 lines (truncate with warning if over)
            lines = plan_md.splitlines()
            if len(lines) > _MAX_PLAN_LINES:
                warnings.warn(
                    f"Unit {i} ({unit.title!r}): plan has {len(lines)} lines, "
                    f"truncating to {_MAX_PLAN_LINES}.",
                    stacklevel=2,
                )
                plan_md = "\n".join(lines[:_MAX_PLAN_LINES])

            # Validate: plan references at least one file from unit's manifest
            manifest = unit.file_manifest
            all_files = manifest.creates + manifest.modifies + manifest.reads
            if all_files:
                referenced = any(f in plan_md for f in all_files)
                if not referenced:
                    warnings.warn(
                        f"Unit {i} ({unit.title!r}): plan does not reference any "
                        f"file from its manifest ({all_files}).",
                        stacklevel=2,
                    )

            result.append(plan_md)

        return result
