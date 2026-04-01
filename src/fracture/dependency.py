"""dependency.py — Pure graph logic for Fracture.

Write-set overlap detection, dependency graph construction, validation,
phase calculation, and dependency rewiring. No LLM calls, no I/O.
"""

from __future__ import annotations

from collections import deque

from fracture.types import DependencyEdge, Phase, Unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_set(unit: Unit) -> set[str]:
    """Return the set of files a unit writes (creates + modifies)."""
    return set(unit.file_manifest.creates) | set(unit.file_manifest.modifies)


def _only_creates(unit: Unit) -> bool:
    """Return True if the unit creates files but does not modify any."""
    return bool(unit.file_manifest.creates) and not unit.file_manifest.modifies


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def derive_dependencies(units: list[Unit]) -> list[DependencyEdge]:
    """For each pair of units, check if their write sets overlap.

    If overlap: create a dependency edge from the logically earlier to the later.
    Write set = creates + modifies.
    Ordering heuristic: creates-only units before modify units; lower index first.
    """
    edges: list[DependencyEdge] = []

    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            a_writes = _write_set(units[i])
            b_writes = _write_set(units[j])
            overlap = a_writes & b_writes
            if not overlap:
                continue

            # Determine ordering: creates-only unit goes first.
            a_only_creates = _only_creates(units[i])
            b_only_creates = _only_creates(units[j])

            if b_only_creates and not a_only_creates:
                # j (creates-only) should precede i (modifies)
                from_unit, to_unit = j, i
            else:
                # Default: lower index (i) goes first
                from_unit, to_unit = i, j

            edges.append(DependencyEdge(
                from_unit=from_unit,
                to_unit=to_unit,
                shared_files=sorted(overlap),
                reason="write-set overlap",
            ))

    return edges


def has_dependency_path(a: int, b: int, edges: list[DependencyEdge]) -> bool:
    """Return True if there is a directed path from a to b OR from b to a.

    Uses BFS in both directions over the directed edge graph.
    """
    # Build adjacency list (directed)
    adj: dict[int, list[int]] = {}
    for edge in edges:
        adj.setdefault(edge.from_unit, []).append(edge.to_unit)

    def _reachable(start: int, target: int) -> bool:
        visited: set[int] = set()
        queue: deque[int] = deque([start])
        while queue:
            node = queue.popleft()
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            for neighbour in adj.get(node, []):
                if neighbour not in visited:
                    queue.append(neighbour)
        return False

    return _reachable(a, b) or _reachable(b, a)


def validate_graph(
    units: list[Unit],
    edges: list[DependencyEdge],
) -> list[tuple[int, int, set[str]]]:
    """Check all pairs with NO dependency path between them.

    If their write sets overlap, return them as conflicts.
    Empty list = valid graph (no conflicts).
    """
    conflicts: list[tuple[int, int, set[str]]] = []

    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            if has_dependency_path(i, j, edges):
                continue
            overlap = _write_set(units[i]) & _write_set(units[j])
            if overlap:
                conflicts.append((i, j, overlap))

    return conflicts


def determine_phases(units: list[Unit], edges: list[DependencyEdge]) -> list[Phase]:
    """Topological sort using Kahn's algorithm.

    Phase 1: units with no incoming edges (roots).
    Phase N: units whose all deps are in phases < N.
    Returns list of Phase objects; Phase.gate = 'validate before proceeding'.
    """
    n = len(units)
    if n == 0:
        return []

    # Compute in-degree and adjacency for Kahn's algorithm
    in_degree: dict[int, int] = {i: 0 for i in range(n)}
    successors: dict[int, list[int]] = {i: [] for i in range(n)}

    for edge in edges:
        in_degree[edge.to_unit] += 1
        successors[edge.from_unit].append(edge.to_unit)

    # Assign phase numbers via iterative layer peeling
    phase_of: dict[int, int] = {}
    current_queue: deque[int] = deque(
        i for i in range(n) if in_degree[i] == 0
    )
    current_phase = 1

    remaining = set(range(n))

    while remaining:
        if not current_queue:
            # Cycle detected — assign remaining units to the next phase to avoid
            # infinite loops, even though the graph is invalid.
            current_queue.extend(sorted(remaining))

        layer: list[int] = []
        next_queue: deque[int] = deque()

        # Drain the current layer
        while current_queue:
            node = current_queue.popleft()
            if node not in remaining:
                continue
            layer.append(node)

        if not layer:
            break

        for node in layer:
            phase_of[node] = current_phase
            remaining.discard(node)
            for successor in successors[node]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0 and successor in remaining:
                    next_queue.append(successor)

        current_queue = next_queue
        current_phase += 1

    # Group by phase number
    phase_map: dict[int, list[int]] = {}
    for unit_idx, phase_num in phase_of.items():
        phase_map.setdefault(phase_num, []).append(unit_idx)

    phases: list[Phase] = []
    for phase_num in sorted(phase_map.keys()):
        unit_indices = sorted(phase_map[phase_num])
        phases.append(Phase(
            phase_number=phase_num,
            bead_ids=[str(i) for i in unit_indices],
            gate="validate before proceeding",
        ))

    return phases


def rewire_dependencies(
    parent_idx: int,
    sub_units: list[Unit],
    existing_edges: list[DependencyEdge],
) -> list[DependencyEdge]:
    """Replace parent_idx in the edge graph with its sub-units.

    Sub-unit indices are assigned starting from the current max index + 1
    (i.e., they are appended after existing unit slots).

    Rules:
    - Edges that pointed INTO the parent (to_unit == parent_idx) now point
      into EVERY sub-unit (fan-out).
    - Edges that went OUT OF the parent (from_unit == parent_idx) now
      originate from the LAST sub-unit (the one that finishes the work).
    - Edges entirely unrelated to the parent are kept as-is.
    - Internal ordering within sub-units (linear chain) is derived by
      derive_dependencies on the sub_units themselves.

    Returns a new edge list with all parent references replaced.
    """
    if not sub_units:
        # Nothing to replace with — drop all edges referencing parent.
        return [e for e in existing_edges
                if e.from_unit != parent_idx and e.to_unit != parent_idx]

    # Determine the base index for sub-units.
    max_existing = max(
        (max(e.from_unit, e.to_unit) for e in existing_edges),
        default=parent_idx,
    )
    # Sub-unit indices start after the highest known index.
    base = max_existing + 1
    sub_indices = list(range(base, base + len(sub_units)))
    last_sub = sub_indices[-1]

    new_edges: list[DependencyEdge] = []

    for edge in existing_edges:
        incoming = edge.to_unit == parent_idx
        outgoing = edge.from_unit == parent_idx

        if incoming and outgoing:
            # Self-loop through parent — skip (shouldn't occur in valid graphs).
            continue
        elif incoming:
            # Fan-out: everything that blocked parent now blocks each sub-unit.
            for sub_idx in sub_indices:
                new_edges.append(DependencyEdge(
                    from_unit=edge.from_unit,
                    to_unit=sub_idx,
                    shared_files=edge.shared_files,
                    reason=edge.reason,
                ))
        elif outgoing:
            # The last sub-unit inherits all outgoing edges of the parent.
            new_edges.append(DependencyEdge(
                from_unit=last_sub,
                to_unit=edge.to_unit,
                shared_files=edge.shared_files,
                reason=edge.reason,
            ))
        else:
            # Unrelated edge — keep as-is.
            new_edges.append(edge)

    # Add internal dependency chain within sub-units (linear: 0→1→2→…).
    sub_dep_edges = derive_dependencies(sub_units)
    for e in sub_dep_edges:
        new_edges.append(DependencyEdge(
            from_unit=sub_indices[e.from_unit],
            to_unit=sub_indices[e.to_unit],
            shared_files=e.shared_files,
            reason=e.reason,
        ))

    # If derive_dependencies found no internal edges, create a linear chain so
    # that the last sub-unit is reachable (preserving the "last sub blocks
    # downstream" invariant even for independent sub-units).
    if not sub_dep_edges and len(sub_indices) > 1:
        for k in range(len(sub_indices) - 1):
            new_edges.append(DependencyEdge(
                from_unit=sub_indices[k],
                to_unit=sub_indices[k + 1],
                shared_files=[],
                reason="sub-unit sequencing",
            ))

    return new_edges


# ---------------------------------------------------------------------------
# Inline tests (run with: python3 -m fracture.dependency)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from fracture.types import FileManifest

    def _unit(creates=(), modifies=(), reads=()):
        return Unit(
            title="test",
            description="",
            deliverable="",
            file_manifest=FileManifest(
                creates=list(creates),
                modifies=list(modifies),
                reads=list(reads),
            ),
            estimated_hours=1.0,
            rationale="",
        )

    print("=== derive_dependencies ===")
    # Two units that share a file
    u0 = _unit(creates=["a.py"])
    u1 = _unit(modifies=["a.py"])
    edges = derive_dependencies([u0, u1])
    assert len(edges) == 1, f"expected 1 edge, got {edges}"
    assert edges[0].from_unit == 0 and edges[0].to_unit == 1, \
        f"expected 0→1, got {edges[0]}"
    print(f"  creates→modifies: {edges[0]}")

    # Creates-only unit should come before modify unit even if index is higher
    u_mod = _unit(modifies=["b.py"])
    u_cre = _unit(creates=["b.py"])
    edges2 = derive_dependencies([u_mod, u_cre])
    assert len(edges2) == 1
    assert edges2[0].from_unit == 1 and edges2[0].to_unit == 0, \
        f"creates-only (idx 1) should precede modify (idx 0), got {edges2[0]}"
    print(f"  creates-only heuristic: {edges2[0]}")

    # No overlap
    u_a = _unit(creates=["x.py"])
    u_b = _unit(creates=["y.py"])
    edges3 = derive_dependencies([u_a, u_b])
    assert edges3 == [], f"expected no edges, got {edges3}"
    print("  no overlap: OK")

    print("\n=== has_dependency_path ===")
    e = [DependencyEdge(0, 1, [], ""), DependencyEdge(1, 2, [], "")]
    assert has_dependency_path(0, 2, e), "0→1→2 should be reachable"
    assert has_dependency_path(2, 0, e), "reverse: 2 should reach 0 via backward search"
    assert not has_dependency_path(0, 3, e), "3 is not in graph"
    print("  forward/backward/missing: OK")

    print("\n=== validate_graph ===")
    ua = _unit(creates=["f.py"])
    ub = _unit(modifies=["f.py"])
    uc = _unit(modifies=["f.py"])
    good_edges = derive_dependencies([ua, ub])  # ua→ub
    # ub and uc both modify f.py but have no path between them → conflict
    # Also ua (creates f.py) and uc (modifies f.py) have no path → also a conflict
    # So we expect conflicts: (0,2) and (1,2)
    conflicts = validate_graph([ua, ub, uc], good_edges)
    assert len(conflicts) == 2, f"expected 2 conflicts, got {conflicts}"
    conflict_pairs = {(c[0], c[1]) for c in conflicts}
    assert (0, 2) in conflict_pairs and (1, 2) in conflict_pairs, \
        f"expected (0,2) and (1,2), got {conflict_pairs}"
    print(f"  conflicts detected: {conflicts}")

    # Full chain: ua→ub→uc (no conflicts)
    full_edges = derive_dependencies([ua, ub, uc])
    conflicts2 = validate_graph([ua, ub, uc], full_edges)
    assert conflicts2 == [], f"expected no conflicts, got {conflicts2}"
    print("  no conflicts with full chain: OK")

    print("\n=== determine_phases ===")
    # Linear chain 0→1→2
    chain_units = [_unit(creates=["a"]), _unit(modifies=["a"], creates=["b"]),
                   _unit(modifies=["b"])]
    chain_edges = derive_dependencies(chain_units)
    phases = determine_phases(chain_units, chain_edges)
    assert len(phases) == 3, f"expected 3 phases, got {phases}"
    assert phases[0].bead_ids == ["0"]
    assert phases[1].bead_ids == ["1"]
    assert phases[2].bead_ids == ["2"]
    print(f"  linear chain phases: {[(p.phase_number, p.bead_ids) for p in phases]}")

    # Two independent units → same phase
    ind_units = [_unit(creates=["p.py"]), _unit(creates=["q.py"])]
    ind_edges = derive_dependencies(ind_units)
    ind_phases = determine_phases(ind_units, ind_edges)
    assert len(ind_phases) == 1, f"expected 1 phase, got {ind_phases}"
    assert set(ind_phases[0].bead_ids) == {"0", "1"}
    print(f"  independent units in same phase: {ind_phases[0].bead_ids}")

    print("\n=== rewire_dependencies ===")
    # parent=1 is between 0→1→2
    p0 = _unit(creates=["x.py"])
    p1 = _unit(modifies=["x.py"], creates=["y.py"])  # parent
    p2 = _unit(modifies=["y.py"])
    parent_edges = derive_dependencies([p0, p1, p2])
    print(f"  original edges: {[(e.from_unit, e.to_unit) for e in parent_edges]}")

    sub_a = _unit(modifies=["x.py"])
    sub_b = _unit(creates=["y.py"])
    rewired = rewire_dependencies(1, [sub_a, sub_b], parent_edges)
    print(f"  rewired edges: {[(e.from_unit, e.to_unit) for e in rewired]}")
    # 0 should now point to both sub-units (fan-out)
    to_targets = {e.to_unit for e in rewired if e.from_unit == 0}
    assert len(to_targets) >= 1, "0 should point to sub-units"
    # 2 should be downstream of last sub-unit
    from_sources = {e.from_unit for e in rewired if e.to_unit == 2}
    assert len(from_sources) >= 1, "2 should depend on a sub-unit"
    print("  rewire fan-out and downstream: OK")

    print("\nAll tests passed.")
