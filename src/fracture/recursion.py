"""recursion.py — Compound unit detection and recursive decomposition for Fracture.

Detects units that are too large to execute in a single session (compound units),
recursively decomposes them via the Analyzer, replaces them in the unit graph,
and rewires all dependency edges. The output is always a flat list of atomic units.

Do NOT call bd CLI.
Do NOT generate plans or instructions.
Do NOT write logs.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from fracture.dependency import derive_dependencies, rewire_dependencies
from fracture.types import DependencyEdge, FractureConfig, Unit

if TYPE_CHECKING:
    from fracture.analyzer import Analyzer


# ---------------------------------------------------------------------------
# Sequential marker words used in compound detection
# ---------------------------------------------------------------------------

_SEQUENTIAL_MARKERS = frozenset(["first", "then", "finally", "step", "phase"])


# ---------------------------------------------------------------------------
# RecursionEngine
# ---------------------------------------------------------------------------


class RecursionEngine:
    """Detects compound units and recursively decomposes them.

    A compound unit is one that is too large to execute in a single session.
    This engine replaces compound units with their sub-units and rewires all
    dependency edges so that the full graph remains consistent.
    """

    def __init__(self, analyzer: "Analyzer", config: FractureConfig) -> None:
        self._analyzer = analyzer
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(
        self,
        units: list[Unit],
        edges: list[DependencyEdge],
        project: str,
        depth: int = 0,
    ) -> tuple[list[Unit], list[DependencyEdge]]:
        """Expand all compound units into atomic sub-units.

        Iterates over the unit list, finding compound units one at a time.
        Each compound unit is:
          1. Re-analyzed with narrowed scope (its own file manifest as context).
          2. Replaced in the list by its sub-units.
          3. All edges referencing the parent index are rewired via
             dependency.rewire_dependencies(), using contiguous index slots.
          4. New intra-sub-unit edges are derived and merged.
          5. The process repeats (recursively, via depth tracking per unit)
             until no compound units remain or max_recursion_depth is reached.

        Args:
            units: List of Unit objects to process.
            edges: Dependency edges referencing indices into units.
            project: Project identifier for TerseContext queries.
            depth: Current recursion depth (used to enforce max_recursion_depth).

        Returns:
            (flat_units, flat_edges) — atomic units and valid dependency edges.
        """
        result_units: list[Unit] = list(units)
        result_edges: list[DependencyEdge] = list(edges)

        # depth_map tracks the recursion depth at which each unit slot was
        # introduced.  Initially every unit is at the caller's depth.
        depth_map: dict[int, int] = {i: depth for i in range(len(result_units))}

        i = 0
        while i < len(result_units):
            unit = result_units[i]
            unit_depth = depth_map.get(i, depth)

            if not self._is_compound(unit):
                i += 1
                continue

            if unit_depth >= self._config.max_recursion_depth:
                warnings.warn(
                    f"Max recursion depth ({self._config.max_recursion_depth}) "
                    f"reached for unit '{unit.title}'. Keeping as-is."
                )
                i += 1
                continue

            # Build artifacts from the unit's file manifest for narrower context.
            all_files = (
                unit.file_manifest.creates
                + unit.file_manifest.modifies
                + unit.file_manifest.reads
            )
            artifacts = [{"path": p, "content": ""} for p in all_files]

            # Re-analyze with narrowed scope.
            try:
                sub_units = await self._analyzer.analyze(
                    task=f"{unit.title}: {unit.description}",
                    project=project,
                    artifacts=artifacts,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.warn(
                    f"Failed to decompose compound unit '{unit.title}': {exc}. "
                    "Keeping as-is."
                )
                i += 1
                continue

            if not sub_units or len(sub_units) <= 1:
                # Cannot decompose further — leave the unit in place.
                i += 1
                continue

            # ------------------------------------------------------------------
            # Replace result_units[i] with sub_units, keeping contiguous indices.
            #
            # Strategy:
            #   - The parent sits at index i.
            #   - We will use the same index slot i for the first sub-unit, and
            #     shift everything after it to the right.
            #   - All existing edges with from_unit/to_unit > i are shifted by
            #     (len(sub_units) - 1).
            #   - Edges referencing the parent (index i) are expanded:
            #       * Incoming edges (to_unit == i) fan-out to ALL sub-units.
            #       * Outgoing edges (from_unit == i) originate from the LAST
            #         sub-unit.
            # ------------------------------------------------------------------

            n_subs = len(sub_units)
            shift = n_subs - 1  # how many extra slots we insert

            # Shift all indices > i upward.
            shifted_edges: list[DependencyEdge] = []
            for e in result_edges:
                new_from = e.from_unit + shift if e.from_unit > i else e.from_unit
                new_to = e.to_unit + shift if e.to_unit > i else e.to_unit
                shifted_edges.append(
                    DependencyEdge(
                        from_unit=new_from,
                        to_unit=new_to,
                        shared_files=e.shared_files,
                        reason=e.reason,
                    )
                )

            # Sub-unit slots: i, i+1, …, i+n_subs-1
            sub_slot_start = i
            sub_slot_end = i + n_subs  # exclusive
            sub_slots = list(range(sub_slot_start, sub_slot_end))
            last_sub_slot = sub_slots[-1]

            # Expand edges that reference the parent slot (now == i after shift,
            # since parent_idx == i and shift only applies to indices > i).
            expanded_edges: list[DependencyEdge] = []
            for e in shifted_edges:
                incoming = e.to_unit == i
                outgoing = e.from_unit == i

                if incoming and outgoing:
                    # Self-loop through parent — drop.
                    continue
                elif incoming:
                    # Fan-out: every external predecessor now blocks all sub-units.
                    for sub_slot in sub_slots:
                        expanded_edges.append(
                            DependencyEdge(
                                from_unit=e.from_unit,
                                to_unit=sub_slot,
                                shared_files=e.shared_files,
                                reason=e.reason,
                            )
                        )
                elif outgoing:
                    # The last sub-unit inherits all outgoing edges of the parent.
                    expanded_edges.append(
                        DependencyEdge(
                            from_unit=last_sub_slot,
                            to_unit=e.to_unit,
                            shared_files=e.shared_files,
                            reason=e.reason,
                        )
                    )
                else:
                    expanded_edges.append(e)

            # Derive intra-sub-unit dependencies and map them to absolute slots.
            intra_edges = derive_dependencies(sub_units)
            for e in intra_edges:
                expanded_edges.append(
                    DependencyEdge(
                        from_unit=sub_slots[e.from_unit],
                        to_unit=sub_slots[e.to_unit],
                        shared_files=e.shared_files,
                        reason=e.reason,
                    )
                )

            # If no intra-edges were derived, create a linear sequencing chain so
            # that the "last sub-unit blocks downstream" invariant holds.
            if not intra_edges and n_subs > 1:
                for k in range(n_subs - 1):
                    expanded_edges.append(
                        DependencyEdge(
                            from_unit=sub_slots[k],
                            to_unit=sub_slots[k + 1],
                            shared_files=[],
                            reason="sub-unit sequencing",
                        )
                    )

            # Replace the parent in the unit list with the sub-units.
            result_units[i : i + 1] = sub_units

            # Update depth_map: shift existing depth entries and assign the new
            # sub-unit slots the next depth level.
            new_depth_map: dict[int, int] = {}
            for slot, d in depth_map.items():
                if slot < i:
                    new_depth_map[slot] = d
                elif slot == i:
                    # Parent slot is gone — its depth will be assigned below.
                    pass
                else:
                    new_depth_map[slot + shift] = d
            for sub_slot in sub_slots:
                new_depth_map[sub_slot] = unit_depth + 1
            depth_map = new_depth_map

            result_edges = expanded_edges

            # Do NOT advance i — re-examine the first sub-unit for compoundness
            # at the new (incremented) depth.

        return result_units, result_edges

    # ------------------------------------------------------------------
    # Compound detection
    # ------------------------------------------------------------------

    def _is_compound(self, unit: Unit) -> bool:
        """Return True if the unit is too large to execute in one session.

        A unit is compound if ANY of these are true:
        - Total file count (creates + modifies) > 6.
        - estimated_hours > config.max_bead_hours.
        - Files span 3 or more distinct top-level directories.
        - Description contains sequential markers (first/then/finally/step/phase).
        """
        fm = unit.file_manifest
        write_files = fm.creates + fm.modifies

        # Check 1: file count
        if len(write_files) > 6:
            return True

        # Check 2: estimated hours
        if unit.estimated_hours > self._config.max_bead_hours:
            return True

        # Check 3: top-level directory span
        top_dirs: set[str] = set()
        for path in write_files:
            # Extract the first path segment (e.g., "src" from "src/foo/bar.py").
            first_segment = path.split("/")[0]
            top_dirs.add(first_segment)
        if len(top_dirs) >= 3:
            return True

        # Check 4: sequential markers in description
        description_lower = unit.description.lower()
        words = set(description_lower.split())
        if words & _SEQUENTIAL_MARKERS:
            return True

        return False
