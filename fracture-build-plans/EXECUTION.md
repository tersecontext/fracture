# Fracture — Master Execution Plan

## Project Root
```
~/maintainer/fracture/          ← project root (main branch)
~/maintainer/fracture-lane-X/   ← worktrees (one per active lane)
```

## Dependency Graph

```
Phase 1 (parallel — no deps):
  A-types        → src/fracture/types.py
  B-config       → src/fracture/config.py
  C-tersecontext → src/fracture/tersecontext.py
  D-model        → src/fracture/model.py

Phase 2 (parallel — all depend only on A):
  E-prompts      → src/fracture/prompts.py       [blocked by A]
  F-dependency   → src/fracture/dependency.py     [blocked by A]
  J-beads        → src/fracture/beads.py          [blocked by A]
  K-logger       → src/fracture/logger.py         [blocked by A]

Phase 3 (parallel — mixed deps from phases 1-2):
  G-analyzer     → src/fracture/analyzer.py       [blocked by C, D, E]
  H-planner      → src/fracture/planner.py        [blocked by D, E]
  I-instructor   → src/fracture/instructor.py     [blocked by D, E]
  M-feedback     → src/fracture/feedback.py       [blocked by J, K]

Phase 4 (series):
  L-recursion    → src/fracture/recursion.py      [blocked by G, F]

Phase 5 (series):
  N-server       → src/fracture/server.py         [blocked by ALL]
```

## Visual Timeline

```
TIME ───────────────────────────────────────────────────────────────►

Phase 1         Phase 2            Phase 3            Phase 4     Phase 5
(foundation)    (core logic)       (orchestration)    (recursion) (integration)

[A-types]──────→[E-prompts]───────→[G-analyzer]──────→[L-recur]──→[N-server]
[B-config]      [F-dependency]─────→               ──→
[C-tersectx]───→                   [H-planner]
[D-model]──────→                   [I-instructor]
                [J-beads]─────────→[M-feedback]
                [K-logger]────────→

    ☕               ☕                 ☕              ☕           ☕
```

## File Conflict Analysis

No parallel lanes share write targets. Each lane creates exactly one file:

| Lane | File | Phase |
|------|------|-------|
| A | src/fracture/types.py | 1 |
| B | src/fracture/config.py | 1 |
| C | src/fracture/tersecontext.py | 1 |
| D | src/fracture/model.py | 1 |
| E | src/fracture/prompts.py | 2 |
| F | src/fracture/dependency.py | 2 |
| J | src/fracture/beads.py | 2 |
| K | src/fracture/logger.py | 2 |
| G | src/fracture/analyzer.py | 3 |
| H | src/fracture/planner.py | 3 |
| I | src/fracture/instructor.py | 3 |
| M | src/fracture/feedback.py | 3 |
| L | src/fracture/recursion.py | 4 |
| N | src/fracture/server.py | 5 |

All lanes within a phase write to different files. Merge conflicts are impossible by construction.

---

## Phase 0: Project Setup

```bash
# ── Create project ────────────────────────────────────────
cd ~/maintainer
mkdir fracture && cd fracture
git init

# ── Project structure ─────────────────────────────────────
mkdir -p src/fracture
touch src/fracture/__init__.py
touch src/fracture/py.typed

# ── Copy root files from zip ──────────────────────────────
cp /path/to/fracture-zip/root/CLAUDE.md .
cp /path/to/fracture-zip/root/FRACTURE_PLAN_V2.md .
cp /path/to/fracture-zip/EXECUTION.md .
mkdir -p lane-plans
cp -r /path/to/fracture-zip/lanes/* lane-plans/

# ── Python project setup ─────────────────────────────────
cat > pyproject.toml << 'EOF'
[project]
name = "fracture"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "mcp>=1.0",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
EOF

# ── Config template ───────────────────────────────────────
cat > fracture.yaml << 'EOF'
tersecontext:
  endpoint: "http://localhost:8000"
beads:
  project_dir: "."
model:
  provider: "claude"
  claude:
    model: "claude-sonnet-4-20250514"
    api_key_env: "ANTHROPIC_API_KEY"
    max_tokens: 4096
  local:
    endpoint: "http://localhost:11434/v1"
    model: "qwen3.5"
    api_key: ""
    max_tokens: 4096
log:
  dir: ".fracture/logs"
defaults:
  max_bead_hours: 3
  max_parallel_lanes: 4
  max_recursion_depth: 4
  max_correction_rounds: 2
EOF

# ── Initial commit ────────────────────────────────────────
git add -A
git commit -m "initial: project structure, config, lane plans"

# ── Initialize beads ─────────────────────────────────────
bd init
echo "Use 'bd' for task tracking. Run 'bd ready --json' to find work." >> AGENTS.md
git add -A && git commit -m "init: beads and AGENTS.md"

# ── Create all beads ─────────────────────────────────────

# Phase 1: Foundation (parallel, no deps)
LANE_A=$(bd create "Core types and schemas" \
  -t task -p 1 \
  --description="types.py — all dataclasses: Unit, FileManifest, FractureMetadata, DependencyEdge, Phase, DecompositionResult, CodebaseContext, FeedbackResult, FractureConfig. JSON serialization." \
  --notes='{"fracture":{"file":"src/fracture/types.py","phase":1}}' \
  --json | jq -r '.id')
echo "A-types: $LANE_A"

LANE_B=$(bd create "Config parser" \
  -t task -p 1 \
  --description="config.py — parse fracture.yaml into FractureConfig. Defaults, env var expansion, validation." \
  --notes='{"fracture":{"file":"src/fracture/config.py","phase":1}}' \
  --json | jq -r '.id')
echo "B-config: $LANE_B"

LANE_C=$(bd create "TerseContext client" \
  -t task -p 1 \
  --description="tersecontext.py — async client for semantic_search, dependency_graph, file_tree queries. Graceful fallback when unavailable." \
  --notes='{"fracture":{"file":"src/fracture/tersecontext.py","phase":1}}' \
  --json | jq -r '.id')
echo "C-tersecontext: $LANE_C"

LANE_D=$(bd create "Model client (Claude + local LLM)" \
  -t task -p 1 \
  --description="model.py — unified LLM client. Claude API and OpenAI-compatible local endpoint. call() and call_json() methods. JSON fence stripping." \
  --notes='{"fracture":{"file":"src/fracture/model.py","phase":1}}' \
  --json | jq -r '.id')
echo "D-model: $LANE_D"

# Phase 2: Core logic (parallel, blocked by A)
LANE_E=$(bd create "Prompt templates (ANALYZE, PLAN, INSTRUCT)" \
  -t task -p 2 \
  --deps blocks:$LANE_A \
  --description="prompts.py — three prompt builder functions. System prompts with JSON schemas. User message assembly from CodebaseContext." \
  --notes='{"fracture":{"file":"src/fracture/prompts.py","phase":2}}' \
  --json | jq -r '.id')
echo "E-prompts: $LANE_E"

LANE_F=$(bd create "Dependency engine" \
  -t task -p 2 \
  --deps blocks:$LANE_A \
  --description="dependency.py — pure functions: derive_dependencies, validate_graph, determine_phases, has_dependency_path, rewire_dependencies. Write-set overlap logic." \
  --notes='{"fracture":{"file":"src/fracture/dependency.py","phase":2}}' \
  --json | jq -r '.id')
echo "F-dependency: $LANE_F"

LANE_J=$(bd create "Beads CLI integration" \
  -t task -p 2 \
  --deps blocks:$LANE_A \
  --description="beads.py — all bd CLI interaction. create_bead, close_bead, show_bead, list_open_beads, create_beads_transactional with rollback." \
  --notes='{"fracture":{"file":"src/fracture/beads.py","phase":2}}' \
  --json | jq -r '.id')
echo "J-beads: $LANE_J"

LANE_K=$(bd create "Audit logger" \
  -t task -p 2 \
  --deps blocks:$LANE_A \
  --description="logger.py — append-only JSONL logger. log_decomposition, log_feedback, log_error. Writes to .fracture/logs/." \
  --notes='{"fracture":{"file":"src/fracture/logger.py","phase":2}}' \
  --json | jq -r '.id')
echo "K-logger: $LANE_K"

# Phase 3: Orchestration (parallel, mixed deps)
LANE_G=$(bd create "Analyzer (LLM Call 1)" \
  -t feature -p 1 \
  --deps blocks:$LANE_C,blocks:$LANE_D,blocks:$LANE_E \
  --description="analyzer.py — orchestrates Call 1 (ANALYZE). Queries TerseContext, builds prompt, calls model, validates file paths, correction rounds." \
  --notes='{"fracture":{"file":"src/fracture/analyzer.py","phase":3}}' \
  --json | jq -r '.id')
echo "G-analyzer: $LANE_G"

LANE_H=$(bd create "Planner (LLM Call 2)" \
  -t feature -p 2 \
  --deps blocks:$LANE_D,blocks:$LANE_E \
  --description="planner.py — orchestrates Call 2 (PLAN). Takes units + edges + context, calls model, returns plan_md per unit." \
  --notes='{"fracture":{"file":"src/fracture/planner.py","phase":3}}' \
  --json | jq -r '.id')
echo "H-planner: $LANE_H"

LANE_I=$(bd create "Instructor (LLM Call 3)" \
  -t feature -p 2 \
  --deps blocks:$LANE_D,blocks:$LANE_E \
  --description="instructor.py — orchestrates Call 3 (INSTRUCT). Takes units + plans + context, calls model, returns claude_md per unit." \
  --notes='{"fracture":{"file":"src/fracture/instructor.py","phase":3}}' \
  --json | jq -r '.id')
echo "I-instructor: $LANE_I"

LANE_M=$(bd create "Feedback tool" \
  -t task -p 3 \
  --deps blocks:$LANE_J,blocks:$LANE_K \
  --description="feedback.py — compares predicted vs actual file changes. Reads bead metadata, calculates accuracy, logs result." \
  --notes='{"fracture":{"file":"src/fracture/feedback.py","phase":3}}' \
  --json | jq -r '.id')
echo "M-feedback: $LANE_M"

# Phase 4: Recursion (series)
LANE_L=$(bd create "Recursion engine" \
  -t feature -p 1 \
  --deps blocks:$LANE_G,blocks:$LANE_F \
  --description="recursion.py — compound detection, recursive sub-decomposition, dependency rewiring. Flattens tree into DAG." \
  --notes='{"fracture":{"file":"src/fracture/recursion.py","phase":4}}' \
  --json | jq -r '.id')
echo "L-recursion: $LANE_L"

# Phase 5: Integration (series, blocked by everything)
LANE_N=$(bd create "MCP server" \
  -t feature -p 1 \
  --deps blocks:$LANE_B,blocks:$LANE_G,blocks:$LANE_H,blocks:$LANE_I,blocks:$LANE_L,blocks:$LANE_J,blocks:$LANE_K,blocks:$LANE_M \
  --description="server.py — FastMCP server. Four tools: decompose, validate, further_decompose, feedback. Wires all modules. Idempotency check. CLI entry point." \
  --notes='{"fracture":{"file":"src/fracture/server.py","phase":5}}' \
  --json | jq -r '.id')
echo "N-server: $LANE_N"

echo ""
echo "=== All beads created. Ready tasks: ==="
bd ready --json
```

---

## Phase 1: Foundation (PARALLEL — 4 lanes)

```bash
cd ~/maintainer/fracture

# Create branches
for lane in a-types b-config c-tersecontext d-model; do
  git checkout -b lane-$lane main
  git checkout main
done

# Create worktrees
git worktree add ../fracture-lane-a lane-a-types
git worktree add ../fracture-lane-b lane-b-config
git worktree add ../fracture-lane-c lane-c-tersecontext
git worktree add ../fracture-lane-d lane-d-model

# Copy lane plans
cp lane-plans/a-types/PLAN.md ../fracture-lane-a/
cp lane-plans/a-types/CLAUDE.md ../fracture-lane-a/
cp lane-plans/b-config/PLAN.md ../fracture-lane-b/
cp lane-plans/b-config/CLAUDE.md ../fracture-lane-b/
cp lane-plans/c-tersecontext/PLAN.md ../fracture-lane-c/
cp lane-plans/c-tersecontext/CLAUDE.md ../fracture-lane-c/
cp lane-plans/d-model/PLAN.md ../fracture-lane-d/
cp lane-plans/d-model/CLAUDE.md ../fracture-lane-d/
```

### Execute (4 parallel agents)

```bash
# Terminal 1: Lane A
cd ~/maintainer/fracture-lane-a
bd update $LANE_A --claim
# ... agent creates src/fracture/types.py ...
git add -A && git commit -m "lane-a: core types and schemas (${LANE_A})"
bd close $LANE_A "All types defined, JSON serialization round-trips"

# Terminal 2: Lane B
cd ~/maintainer/fracture-lane-b
bd update $LANE_B --claim
# ... agent creates src/fracture/config.py ...
git add -A && git commit -m "lane-b: config parser (${LANE_B})"
bd close $LANE_B "Config parser complete, defaults and validation working"

# Terminal 3: Lane C
cd ~/maintainer/fracture-lane-c
bd update $LANE_C --claim
# ... agent creates src/fracture/tersecontext.py ...
git add -A && git commit -m "lane-c: tersecontext client (${LANE_C})"
bd close $LANE_C "TerseContext client complete, fallback working"

# Terminal 4: Lane D
cd ~/maintainer/fracture-lane-d
bd update $LANE_D --claim
# ... agent creates src/fracture/model.py ...
git add -A && git commit -m "lane-d: model client (${LANE_D})"
bd close $LANE_D "Model client complete, both providers tested"
```

### ☕ BREAK — Merge Phase 1

```bash
cd ~/maintainer/fracture
for lane in a-types b-config c-tersecontext d-model; do
  git merge lane-$lane --no-ff -m "merge: lane-$lane"
  git worktree remove ../fracture-lane-${lane#*-}  2>/dev/null
  git worktree remove ../fracture-lane-$(echo $lane | cut -c1) 2>/dev/null
  git branch -d lane-$lane
done

# Clean up worktrees
git worktree remove ../fracture-lane-a 2>/dev/null
git worktree remove ../fracture-lane-b 2>/dev/null
git worktree remove ../fracture-lane-c 2>/dev/null
git worktree remove ../fracture-lane-d 2>/dev/null

bd ready --json
# → Should show: E-prompts, F-dependency, J-beads, K-logger
```

---

## Phase 2: Core Logic (PARALLEL — 4 lanes)

```bash
cd ~/maintainer/fracture

for lane in e-prompts f-dependency j-beads k-logger; do
  git checkout -b lane-$lane main
  git checkout main
done

git worktree add ../fracture-lane-e lane-e-prompts
git worktree add ../fracture-lane-f lane-f-dependency
git worktree add ../fracture-lane-j lane-j-beads
git worktree add ../fracture-lane-k lane-k-logger

cp lane-plans/e-prompts/PLAN.md ../fracture-lane-e/
cp lane-plans/e-prompts/CLAUDE.md ../fracture-lane-e/
cp lane-plans/f-dependency/PLAN.md ../fracture-lane-f/
cp lane-plans/f-dependency/CLAUDE.md ../fracture-lane-f/
cp lane-plans/j-beads/PLAN.md ../fracture-lane-j/
cp lane-plans/j-beads/CLAUDE.md ../fracture-lane-j/
cp lane-plans/k-logger/PLAN.md ../fracture-lane-k/
cp lane-plans/k-logger/CLAUDE.md ../fracture-lane-k/
```

### Execute (4 parallel agents)

```bash
# Terminal 1: Lane E
cd ~/maintainer/fracture-lane-e
bd update $LANE_E --claim
git add -A && git commit -m "lane-e: prompt templates (${LANE_E})"
bd close $LANE_E "All three prompts complete, manually tested"

# Terminal 2: Lane F
cd ~/maintainer/fracture-lane-f
bd update $LANE_F --claim
git add -A && git commit -m "lane-f: dependency engine (${LANE_F})"
bd close $LANE_F "Dependency engine complete, all graph operations tested"

# Terminal 3: Lane J
cd ~/maintainer/fracture-lane-j
bd update $LANE_J --claim
git add -A && git commit -m "lane-j: beads cli integration (${LANE_J})"
bd close $LANE_J "Beads client complete, transactional creation tested"

# Terminal 4: Lane K
cd ~/maintainer/fracture-lane-k
bd update $LANE_K --claim
git add -A && git commit -m "lane-k: audit logger (${LANE_K})"
bd close $LANE_K "Logger complete, all event types tested"
```

### ☕ BREAK — Merge Phase 2

```bash
cd ~/maintainer/fracture
for lane in e-prompts f-dependency j-beads k-logger; do
  git merge lane-$lane --no-ff -m "merge: lane-$lane"
  git branch -d lane-$lane
done
git worktree remove ../fracture-lane-e 2>/dev/null
git worktree remove ../fracture-lane-f 2>/dev/null
git worktree remove ../fracture-lane-j 2>/dev/null
git worktree remove ../fracture-lane-k 2>/dev/null

bd ready --json
# → Should show: G-analyzer, H-planner, I-instructor, M-feedback
```

---

## Phase 3: Orchestration (PARALLEL — 4 lanes)

```bash
cd ~/maintainer/fracture

for lane in g-analyzer h-planner i-instructor m-feedback; do
  git checkout -b lane-$lane main
  git checkout main
done

git worktree add ../fracture-lane-g lane-g-analyzer
git worktree add ../fracture-lane-h lane-h-planner
git worktree add ../fracture-lane-i lane-i-instructor
git worktree add ../fracture-lane-m lane-m-feedback

cp lane-plans/g-analyzer/PLAN.md ../fracture-lane-g/
cp lane-plans/g-analyzer/CLAUDE.md ../fracture-lane-g/
cp lane-plans/h-planner/PLAN.md ../fracture-lane-h/
cp lane-plans/h-planner/CLAUDE.md ../fracture-lane-h/
cp lane-plans/i-instructor/PLAN.md ../fracture-lane-i/
cp lane-plans/i-instructor/CLAUDE.md ../fracture-lane-i/
cp lane-plans/m-feedback/PLAN.md ../fracture-lane-m/
cp lane-plans/m-feedback/CLAUDE.md ../fracture-lane-m/
```

### Execute (4 parallel agents)

```bash
# Terminal 1: Lane G
cd ~/maintainer/fracture-lane-g
bd update $LANE_G --claim
git add -A && git commit -m "lane-g: analyzer (${LANE_G})"
bd close $LANE_G "Analyzer complete, validation and correction working"

# Terminal 2: Lane H
cd ~/maintainer/fracture-lane-h
bd update $LANE_H --claim
git add -A && git commit -m "lane-h: planner (${LANE_H})"
bd close $LANE_H "Planner complete, generates specific plans"

# Terminal 3: Lane I
cd ~/maintainer/fracture-lane-i
bd update $LANE_I --claim
git add -A && git commit -m "lane-i: instructor (${LANE_I})"
bd close $LANE_I "Instructor complete, generates scoped instructions"

# Terminal 4: Lane M
cd ~/maintainer/fracture-lane-m
bd update $LANE_M --claim
git add -A && git commit -m "lane-m: feedback tool (${LANE_M})"
bd close $LANE_M "Feedback tool complete, accuracy calculation tested"
```

### ☕ BREAK — Merge Phase 3

```bash
cd ~/maintainer/fracture
for lane in g-analyzer h-planner i-instructor m-feedback; do
  git merge lane-$lane --no-ff -m "merge: lane-$lane"
  git branch -d lane-$lane
done
git worktree remove ../fracture-lane-g 2>/dev/null
git worktree remove ../fracture-lane-h 2>/dev/null
git worktree remove ../fracture-lane-i 2>/dev/null
git worktree remove ../fracture-lane-m 2>/dev/null

bd ready --json
# → Should show: L-recursion
```

---

## Phase 4: Recursion (SERIES — 1 lane)

```bash
cd ~/maintainer/fracture
git checkout -b lane-l-recursion main
git checkout main
git worktree add ../fracture-lane-l lane-l-recursion
cp lane-plans/l-recursion/PLAN.md ../fracture-lane-l/
cp lane-plans/l-recursion/CLAUDE.md ../fracture-lane-l/
```

### Execute

```bash
cd ~/maintainer/fracture-lane-l
bd update $LANE_L --claim
git add -A && git commit -m "lane-l: recursion engine (${LANE_L})"
bd close $LANE_L "Recursion engine complete, rewiring tested"
```

### ☕ BREAK — Merge Phase 4

```bash
cd ~/maintainer/fracture
git merge lane-l-recursion --no-ff -m "merge: lane-l recursion engine"
git worktree remove ../fracture-lane-l 2>/dev/null
git branch -d lane-l-recursion

bd ready --json
# → Should show: N-server
```

---

## Phase 5: Integration (SERIES — 1 lane)

```bash
cd ~/maintainer/fracture
git checkout -b lane-n-server main
git checkout main
git worktree add ../fracture-lane-n lane-n-server
cp lane-plans/n-server/PLAN.md ../fracture-lane-n/
cp lane-plans/n-server/CLAUDE.md ../fracture-lane-n/
```

### Execute

```bash
cd ~/maintainer/fracture-lane-n
bd update $LANE_N --claim
git add -A && git commit -m "lane-n: mcp server (${LANE_N})"
bd close $LANE_N "MCP server complete, all four tools working end-to-end"
```

### ☕ BREAK — Final merge and tag

```bash
cd ~/maintainer/fracture
git merge lane-n-server --no-ff -m "merge: lane-n mcp server"
git worktree remove ../fracture-lane-n 2>/dev/null
git branch -d lane-n-server
git tag v0.1.0

echo "=== Fracture v0.1.0 complete ==="
bd stats
```

---

## Schedule

| Phase | Lanes | Parallel | Hours | Cumulative |
|-------|-------|----------|-------|------------|
| 0 | Setup | — | 0.5 | 0.5 |
| 1 | A, B, C, D | 4 agents | 1-2 | 2.5 |
| 2 | E, F, J, K | 4 agents | 1-2 | 4.5 |
| 3 | G, H, I, M | 4 agents | 2-3 | 7.5 |
| 4 | L | 1 agent | 2 | 9.5 |
| 5 | N | 1 agent | 2-3 | 12.5 |

**Total: ~12-13 hours with 4 parallel agents.**
**Total serial (1 agent): ~20-25 hours.**
