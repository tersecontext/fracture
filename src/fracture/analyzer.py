"""analyzer.py — Orchestrates LLM Call 1 (ANALYZE) for Fracture.

Queries TerseContext for codebase context, builds the ANALYZE prompt,
calls the model, validates the response, and handles correction rounds.

Do NOT call bd CLI (use beads.py for that).
Do NOT write logs (use logger.py for that).
Do NOT handle recursion (use recursion.py for that).
"""

from __future__ import annotations

from fracture.types import (
    CodebaseContext,
    CodeResult,
    FileManifest,
    FractureConfig,
    Unit,
)
from fracture.tersecontext import TerseContextClient
from fracture.model import ModelClient, JsonParseError
from fracture.prompts import build_analyze_prompt


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AnalysisError(Exception):
    """Raised when analysis fails after exhausting all correction rounds."""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class Analyzer:
    """Orchestrates LLM Call 1: query context, build prompt, call model,
    validate and correct the response."""

    def __init__(
        self,
        tc_client: TerseContextClient,
        model: ModelClient,
        config: FractureConfig,
    ) -> None:
        self._tc_client = tc_client
        self._model = model
        self._config = config

    async def analyze(
        self,
        task: str,
        project: str,
        artifacts: list[dict] | None = None,
        context: CodebaseContext | None = None,
    ) -> list[Unit]:
        """Decompose a task into validated Units.

        Steps:
        1. Query TerseContext for context (or build from artifacts fallback).
        2. Build ANALYZE prompt.
        3. Call model.call_json().
        4. Parse response into list[Unit].
        5. Validate file paths against file tree.
        6. Fix creates/modifies misclassification.
        7. If validation issues remain, send correction prompt (max
           config.max_correction_rounds rounds). Raise AnalysisError after
           max rounds.
        8. Return validated units.

        Args:
            task: Natural language description of the task to decompose.
            project: Project identifier for TerseContext queries.
            artifacts: Optional list of {"path": str, "content": str} dicts
                       used when TerseContext is unavailable.

        Returns:
            Validated list of Unit objects.

        Raises:
            AnalysisError: When the response cannot be corrected within the
                           allowed number of rounds, or when the model returns
                           unparseable JSON.
        """
        # ---------------------------------------------------------------
        # Step 1: Get codebase context (use pre-built if provided)
        # ---------------------------------------------------------------
        if context is None:
            context = await self._get_context(task, project, artifacts)

        # ---------------------------------------------------------------
        # Step 2 & 3: Build prompt and call model
        # ---------------------------------------------------------------
        system_prompt, user_message = build_analyze_prompt(task, context)

        try:
            response = await self._model.call_json(system_prompt, user_message)
        except JsonParseError as exc:
            raise AnalysisError(
                f"Model returned non-JSON on initial call: {exc}"
            ) from exc

        # ---------------------------------------------------------------
        # Step 4: Parse response into list[Unit]
        # ---------------------------------------------------------------
        units = _parse_units(response)

        # ---------------------------------------------------------------
        # Steps 5 & 6: Validate and fix misclassifications
        # ---------------------------------------------------------------
        file_tree_set = set(context.file_tree)
        issues = _validate_units(units, file_tree_set)

        if not issues:
            return units

        # ---------------------------------------------------------------
        # Step 7: Correction rounds
        # ---------------------------------------------------------------
        max_rounds = self._config.max_correction_rounds
        conversation_user = user_message  # preserve for context continuity

        for round_num in range(1, max_rounds + 1):
            correction_message = _build_correction_message(
                conversation_user, issues
            )

            try:
                response = await self._model.call_json(
                    system_prompt, correction_message
                )
            except JsonParseError as exc:
                if round_num == max_rounds:
                    raise AnalysisError(
                        f"Model returned non-JSON after {round_num} correction "
                        f"round(s): {exc}"
                    ) from exc
                # Try another round with the same issues list
                continue

            units = _parse_units(response)
            issues = _validate_units(units, file_tree_set)

            if not issues:
                return units

            # Update conversation context for the next round
            conversation_user = correction_message

        raise AnalysisError(
            f"Analysis failed after {max_rounds} correction round(s). "
            f"Remaining issues: {issues}"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_context(
        self,
        task: str,
        project: str,
        artifacts: list[dict] | None,
    ) -> CodebaseContext:
        """Return CodebaseContext from TerseContext or artifacts fallback."""
        # Trigger availability check lazily, then delegate to get_context.
        context = await self._tc_client.get_context(task, project)

        if self._tc_client.is_available():
            return context

        # TerseContext unavailable — build minimal context from artifacts.
        artifact_list = artifacts or []
        return CodebaseContext(
            file_tree=[a["path"] for a in artifact_list],
            search_results=[
                CodeResult(
                    path=a["path"],
                    content=a.get("description", ""),
                    score=1.0,
                    node_type="file",
                )
                for a in artifact_list
            ],
            dependency_edges=[],
            architecture_summary="",
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_units(response: dict) -> list[Unit]:
    """Parse the raw model response dict into a list of Unit objects.

    Tolerates missing fields where possible by defaulting to empty values.
    Raises AnalysisError if the 'units' key is absent or malformed.
    """
    raw_units = response.get("units")
    if not isinstance(raw_units, list):
        raise AnalysisError(
            f"Model response missing 'units' list. Got: {response!r}"
        )

    units: list[Unit] = []
    for i, raw in enumerate(raw_units):
        if not isinstance(raw, dict):
            raise AnalysisError(
                f"Unit {i} is not a dict: {raw!r}"
            )
        try:
            unit = Unit.from_json(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisError(
                f"Failed to parse unit {i}: {exc}. Raw: {raw!r}"
            ) from exc
        units.append(unit)

    return units


def _normalize_path(path: str) -> str:
    """Strip common absolute prefixes so paths match the relative file tree."""
    for prefix in ("/app/", "./"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    return path.lstrip("/")


def _validate_units(
    units: list[Unit],
    file_tree_set: set[str],
) -> list[str]:
    """Validate units against the file tree; mutate misclassifications in-place.

    Performs two checks:
    - Paths in `modifies` must exist in the file tree.
    - Paths in `creates` that already exist are moved to `modifies`.
    - Each unit must have at least one file in creates or modifies.

    Returns a list of issue strings (empty list means all valid).
    """
    issues: list[str] = []

    for unit in units:
        fm: FileManifest = unit.file_manifest
        # Normalize all paths to relative form
        fm.creates = [_normalize_path(p) for p in fm.creates]
        fm.modifies = [_normalize_path(p) for p in fm.modifies]
        fm.reads = [_normalize_path(p) for p in fm.reads]

    for unit in units:
        fm: FileManifest = unit.file_manifest

        # Check modifies paths exist (skip if file tree is empty — no ground truth)
        if file_tree_set:
            for path in fm.modifies:
                if path not in file_tree_set:
                    issues.append(
                        f"{path} listed in modifies but does not exist in codebase"
                    )

        # Fix creates→modifies misclassification
        new_creates: list[str] = []
        for path in fm.creates:
            if path in file_tree_set:
                fm.modifies.append(path)
                issues.append(
                    f"{path} listed in creates but already exists — moved to modifies"
                )
            else:
                new_creates.append(path)
        fm.creates = new_creates

        # At least one file must be touched
        if not (fm.creates or fm.modifies):
            issues.append(
                f'Unit "{unit.title}" has no files in creates or modifies'
            )

    return issues


def _build_correction_message(
    previous_user_message: str,
    issues: list[str],
) -> str:
    """Build a correction prompt that references the previous context."""
    bullet_lines = "\n".join(f"- {issue}" for issue in issues)
    return (
        f"{previous_user_message}\n\n"
        "Your previous decomposition had issues:\n"
        f"{bullet_lines}\n\n"
        "Please fix and respond with the corrected JSON."
    )
