"""instructor.py — LLM Call 3 (INSTRUCT) orchestration for Fracture.

Takes analyzed units, plans, and TerseContext codebase context,
calls the model, and returns claude_md content per unit.
"""

from __future__ import annotations

import warnings

from fracture.model import ModelClient
from fracture.prompts import build_instruct_prompt
from fracture.types import CodebaseContext, Unit

_MAX_INSTRUCT_LINES = 50


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InstructionError(Exception):
    """Raised when instruction generation fails or produces invalid output."""


# ---------------------------------------------------------------------------
# Instructor
# ---------------------------------------------------------------------------

class Instructor:
    """Orchestrates LLM Call 3: INSTRUCT."""

    def __init__(self, model: ModelClient) -> None:
        self._model = model

    async def generate_instructions(
        self,
        units: list[Unit],
        plans: list[str],
        context: CodebaseContext,
    ) -> list[str]:
        """Generate claude_md strings for each unit.

        Returns a list of claude_md strings, one per unit, in unit order.

        Raises:
            InstructionError: if the model response is missing instructions for
                              any unit, or if the response cannot be parsed.
        """
        if not units:
            return []

        system_prompt, user_message = build_instruct_prompt(units, plans, context)

        try:
            response = await self._model.call_json(system_prompt, user_message)
        except Exception as exc:
            raise InstructionError(
                f"Model call failed during instruction generation: {exc}"
            ) from exc

        raw_instructions = response.get("instructions")
        if not isinstance(raw_instructions, list):
            raise InstructionError(
                f"Expected 'instructions' list in model response, got: "
                f"{type(raw_instructions)}"
            )

        # Index instructions by unit_index
        instructions_by_index: dict[int, str] = {}
        for entry in raw_instructions:
            if not isinstance(entry, dict):
                raise InstructionError(
                    f"Instruction entry is not a dict: {entry!r}"
                )
            unit_index = entry.get("unit_index")
            claude_md = entry.get("claude_md", "")
            if unit_index is None:
                raise InstructionError(
                    f"Instruction entry missing 'unit_index': {entry!r}"
                )
            instructions_by_index[int(unit_index)] = claude_md

        # Validate: one instruction per unit
        missing = [i for i in range(len(units)) if i not in instructions_by_index]
        if missing:
            raise InstructionError(
                f"Missing instructions for unit indices: {missing}"
            )

        # Build result list in unit order, applying per-instruction validation
        result: list[str] = []
        for i, unit in enumerate(units):
            claude_md = instructions_by_index[i]

            # Validate: instruction under 50 lines (truncate with warning if over)
            lines = claude_md.splitlines()
            if len(lines) > _MAX_INSTRUCT_LINES:
                warnings.warn(
                    f"Unit {i} ({unit.title!r}): instruction has {len(lines)} lines, "
                    f"truncating to {_MAX_INSTRUCT_LINES}.",
                    stacklevel=2,
                )
                claude_md = "\n".join(lines[:_MAX_INSTRUCT_LINES])

            # Validate: instruction contains a "Do NOT" section (warn if missing)
            if "Do NOT" not in claude_md and "do not" not in claude_md.lower():
                warnings.warn(
                    f"Unit {i} ({unit.title!r}): instruction does not contain a "
                    f"'Do NOT' section.",
                    stacklevel=2,
                )

            result.append(claude_md)

        return result
