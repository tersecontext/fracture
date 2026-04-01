# Fracture — System Plan v2

## What Fracture Is

Fracture is an MCP server that decomposes large tasks into dependency-ordered beads. It queries TerseContext for codebase intelligence, splits work along file boundaries to prevent merge conflicts, and creates beads in `bd` with self-contained plans and agent instructions.

Fracture does not execute beads. It does not manage worktrees. It does not spawn agents. It creates beads and logs what it did.

## The Stack

```
TerseContext (tersecontext/tersecontext)
  → Codebase knowledge graph (Tree-sitter + runtime traces)
  → Neo4j (graph) + Qdrant (vectors)
  → Answers: "what code is relevant to X?"

Fracture (this system)
  → Receives task from an LLM
  → Queries TerseContext for relevant code
  → Calls a model (Claude API or local LLM) to reason about decomposition
  → Decomposes task into beads with file manifests
  → Creates beads in bd (or outputs dry-run preview)
  → Logs everything

Beads (steveyegge/beads)
  → Stores beads in Dolt
  → Tracks dependencies, ready queue, claiming
  → Agents pick up work via bd ready

[Executor] (separate repo, not Fracture's concern)
  → Picks up beads, runs agents, manages worktrees
```

## Input

An LLM calls Fracture's MCP tool with:

```json
{
  "task": "string — the big plan, described by the calling LLM",
  "project": "string — project identifier for TerseContext queries",
  "dry_run": false,
  "constraints": {
    "max_bead_hours": 3,
    "max_parallel_lanes": 4,
    "max_recursion_depth": 4
  }
}
```

The calling LLM does not pass artifacts. Fracture gets its own context by querying TerseContext.

When `dry_run` is true, Fracture does everything except create beads in `bd`. It returns the proposed beads, phases, and dependency graph for review. A human or LLM inspects the output and then calls again with `dry_run: false`.

## Output

When `dry_run: false`: beads created in `bd`, audit log written to disk.

When `dry_run: true`: proposed beads returned in the response, nothing written to `bd`, log still written (marked as dry run).

## Core Rule

**Parallel beads must not share write targets.**

If two beads both modify the same file, they are serial — one depends on the other. This is the only rule that governs the dependency graph. Parallel lanes, phase gates, and scheduling all derive from this.

---

## Model Integration

Fracture calls an LLM to reason about decomposition. It does not contain the intelligence itself — it orchestrates queries to TerseContext and model calls, then applies deterministic rules (file overlap, dependency derivation, validation) to the model's output.

### Supported Providers

**Claude CLI / API:**
```
POST https://api.anthropic.com/v1/messages
Model: claude-sonnet-4-20250514
Auth: API key via environment variable
```

**Local LLM (OpenAI-compatible):**
```
POST http://localhost:11434/v1/chat/completions  (Ollama)
POST http://localhost:8000/v1/chat/completions   (vLLM)
Model: qwen3.5, llama3.3-70b, etc.
Auth: none or configurable
```

Both use the same prompts. The local LLM path uses the OpenAI-compatible chat completions format since Ollama, vLLM, and TGI all support it.

### Model Call Architecture

Fracture makes **three distinct LLM calls** per decomposition. Each call has a specific purpose, a specific prompt, and a specific output schema. The calls are sequential — each builds on the previous.

```
Call 1: ANALYZE
  Input:  task description + TerseContext results
  Output: list of units of work with predicted file manifests
  
Call 2: PLAN
  Input:  units of work + file manifests + dependency graph
  Output: plan_md content for each bead (~100-150 lines each)
  
Call 3: INSTRUCT
  Input:  plans + TerseContext code excerpts
  Output: claude_md content for each bead (~30-50 lines each)
```

Splitting into three calls keeps each prompt focused and each output parseable. A single mega-call that does all three tends to degrade in quality, especially on smaller local models.

---

## Prompts

### Call 1: ANALYZE

**System prompt:**

```
You are a senior staff engineer decomposing a task into independent units
of work for parallel execution by AI coding agents.

You will receive:
1. A task description
2. Codebase context from a knowledge graph (file contents, dependency
   edges, call graphs)

Your job:
- Identify the distinct units of work needed to complete this task
- For each unit, predict exactly which files will be CREATED, MODIFIED,
  or READ
- Ensure units that modify the same file are marked as sequential
- Prefer splitting along file boundaries — two units that touch
  different files can run in parallel

CRITICAL RULES:
- A unit must have a single, concrete deliverable
- A unit must be completable by one agent in one session (under 3 hours)
- If a unit touches files in 3+ unrelated modules, split it further
- New files (creates) never conflict — only modifications to existing
  files cause conflicts
- Be precise about file paths. Use the exact paths from the codebase
  context provided.

Respond ONLY with valid JSON matching this schema:
{
  "units": [
    {
      "title": "string — short descriptive title",
      "description": "string — 2-3 sentences on what this unit does",
      "deliverable": "string — the single concrete output",
      "file_manifest": {
        "creates": ["string — exact file paths"],
        "modifies": ["string — exact file paths"],
        "reads": ["string — exact file paths"]
      },
      "estimated_hours": number,
      "rationale": "string — why this is a separate unit"
    }
  ],
  "sequencing_notes": "string — explain which units must be serial and why"
}
```

**User message template:**

```
## Task
{task_description}

## Codebase Context

### File Tree
{tersecontext.file_tree}

### Relevant Code
{for each file from TerseContext:}
--- {file.path} ---
{file.content}

### Dependency Graph
{tersecontext.dependency_edges}

### Architecture Notes
{tersecontext.architecture_summary}
```

**Validation after Call 1:**

Before proceeding, Fracture validates the model's output:

1. Parse JSON — if parse fails, retry once with a "fix your JSON" prompt
2. Check all file paths in `modifies` exist in the TerseContext file tree — if a path doesn't exist, flag it (could be a hallucination or a legitimate new path the model confused with `creates`)
3. Check all file paths in `creates` do NOT exist in the TerseContext file tree — if they do, move them to `modifies`
4. Run the write-set overlap check (Step 5 of the algorithm) to derive dependencies
5. Check estimated_hours against max_bead_hours — flag any unit over the threshold for recursion

If validation finds issues, Fracture sends a correction prompt:

```
Your previous decomposition had issues:
{list of issues}

Please fix and respond with the corrected JSON.
```

Maximum 2 correction rounds. If still invalid after corrections, Fracture returns an error to the caller rather than creating bad beads.

### Call 2: PLAN

**System prompt:**

```
You are writing detailed implementation plans for AI coding agents.
Each plan will be stored in a bead (task tracker) and read by an agent
that will execute the work independently.

You will receive a list of units of work with their file manifests and
dependency relationships. For each unit, write a plan document.

Each plan must include:
- What to build (specific, actionable)
- Why this is a separate unit (what files it touches, what it enables)
- The file manifest (creates/modifies/reads)
- Completion criteria (how the agent knows it's done)
- What this unit unblocks when complete
- Key context from the codebase (relevant code excerpts to reference)

Keep each plan under 150 lines. Be specific about file paths and
function names. Do not be generic.

Respond ONLY with valid JSON:
{
  "plans": [
    {
      "unit_index": number,
      "plan_md": "string — the full plan, markdown formatted"
    }
  ]
}
```

**User message:** the units from Call 1, plus the dependency graph derived in validation, plus relevant code excerpts from TerseContext.

### Call 3: INSTRUCT

**System prompt:**

```
You are writing scoped agent instructions (CLAUDE.md files) for AI
coding agents. Each instruction set will be read by a single agent
working in an isolated git worktree.

The agent will ONLY see your instructions and the files in its worktree.
It will NOT see the other beads, the full codebase, or the overall plan.
Your instructions must be self-contained.

For each unit, write a CLAUDE.md that includes:
- Project context (1-2 sentences)
- What this specific task is
- Key files to read and modify (exact paths)
- Tech stack and constraints
- What NOT to do (prevent scope creep)
- Rules (single file, no localStorage, etc. — as appropriate)

Keep each instruction set under 50 lines. Be direct. No preamble.

Respond ONLY with valid JSON:
{
  "instructions": [
    {
      "unit_index": number,
      "claude_md": "string — the full CLAUDE.md content"
    }
  ]
}
```

**User message:** the units and plans from previous calls, plus the relevant code context each agent will need.

---

## TerseContext Interface Contract

Fracture queries TerseContext at specific points during decomposition. The interface is defined here even though TerseContext's query API is still being built. Fracture is built against this contract.

### Query: semantic_search

```json
{
  "query": "string — natural language description of what to find",
  "project": "string — project identifier",
  "max_results": 10
}
```

Returns:
```json
{
  "results": [
    {
      "path": "string — file path",
      "content": "string — file content or relevant excerpt",
      "score": number,
      "node_type": "file | function | class | module"
    }
  ]
}
```

Used in: Step 2, when Fracture needs to find code relevant to the task.

### Query: dependency_graph

```json
{
  "paths": ["string — file paths to get dependencies for"],
  "project": "string",
  "depth": 2
}
```

Returns:
```json
{
  "edges": [
    {
      "from": "string — file path",
      "to": "string — file path",
      "type": "imports | calls | extends | tests"
    }
  ]
}
```

Used in: Step 4, when Fracture needs to understand blast radius of changes.

### Query: file_tree

```json
{
  "project": "string",
  "path_prefix": "string — optional, filter by directory"
}
```

Returns:
```json
{
  "files": ["string — all file paths in the project"]
}
```

Used in: validation, to verify that file paths in manifests are real.

### Fallback

If TerseContext is unavailable, Fracture falls back to accepting artifacts inline in the `decompose` call:

```json
{
  "task": "...",
  "project": "...",
  "artifacts": [
    {"path": "src/auth.js", "content": "..."}
  ]
}
```

This allows Fracture to work without TerseContext during development or for projects that haven't been indexed.

---

## Decomposition Algorithm

### Step 1: Query TerseContext

Extract key topics from the task description. For each topic, call `semantic_search`. Aggregate results. Call `dependency_graph` on the returned files to understand connections. Call `file_tree` to get the complete project structure.

This is deterministic code, not an LLM call.

### Step 2: LLM Call 1 — ANALYZE

Send the task + TerseContext results to the model. Get back units of work with file manifests.

### Step 3: Validate analysis

Deterministic validation:
- Parse JSON
- Verify file paths against TerseContext file tree
- Correct creates/modifies misclassification
- Flag units over max_bead_hours for recursion
- Send correction prompt if needed (max 2 rounds)

### Step 4: Derive dependencies

Deterministic. For each pair of units, check write-set overlap. If overlap exists, add dependency edge. This is code, not an LLM call.

```python
def derive_dependencies(units):
    edges = []
    for i, a in enumerate(units):
        for j, b in enumerate(units):
            if i >= j:
                continue
            a_writes = set(a.creates + a.modifies)
            b_writes = set(b.creates + b.modifies)
            overlap = a_writes & b_writes
            if overlap:
                # Determine order from sequencing_notes or topological hint
                edges.append((earlier(a, b), later(a, b), overlap))
    return edges
```

### Step 5: Check for compound units (recurse)

Deterministic check per unit:
- `len(file_manifest.modifies) + len(file_manifest.creates) > 6` → compound
- `estimated_hours > max_bead_hours` → compound
- Files span 3+ top-level directories → compound

If compound: re-enter at Step 1 with that unit's scope narrowed. Query TerseContext for only the files in that unit's manifest. Run Call 1 again with the sub-scope. Replace the compound unit with its sub-units. Rewire dependencies:

```
When parent bead P is replaced by sub-beads S1, S2, S3:
  - Everything that blocked P now blocks all of S1, S2, S3
  - Everything that P blocked now waits for ALL of S1, S2, S3
    (unless only a subset of sub-beads produce the files that
    the downstream bead reads — then only those sub-beads block it)
```

Recursion depth tracked. Stop at max_recursion_depth. If still compound, log a warning and create the bead as-is with a note that it may be too large.

### Step 6: Validate the graph

Deterministic. Final safety check:

```python
def validate_graph(units, edges):
    conflicts = []
    for i, a in enumerate(units):
        for j, b in enumerate(units):
            if i >= j:
                continue
            if not has_dependency_path(a, b, edges):
                # These could run in parallel
                a_writes = set(a.creates + a.modifies)
                b_writes = set(b.creates + b.modifies)
                overlap = a_writes & b_writes
                if overlap:
                    conflicts.append((a, b, overlap))
    return conflicts
```

If conflicts found: add dependency edges to resolve. Re-derive phases.

### Step 7: Determine phases

Deterministic. Topological sort by dependency depth:

```python
def determine_phases(units, edges):
    phases = []
    remaining = set(units)
    while remaining:
        # Find units whose dependencies are all in previous phases
        ready = [u for u in remaining
                 if all(dep in assigned for dep in u.dependencies)]
        phases.append(ready)
        assigned.update(ready)
        remaining -= set(ready)
    return phases
```

### Step 8: LLM Call 2 — PLAN

Send units + dependency graph + TerseContext excerpts. Get back plan_md for each bead.

### Step 9: LLM Call 3 — INSTRUCT

Send units + plans + relevant code context. Get back claude_md for each bead.

### Step 10: Dry-run gate

If `dry_run: true`: return the proposed beads, phases, and graph. Stop here. Do not create beads.

If `dry_run: false`: proceed to Step 11.

### Step 11: Create beads in bd (transactional)

Create all beads. If any `bd create` fails, close all previously created beads from this decomposition with a "decomposition failed — partial cleanup" reason and return an error.

```python
created_ids = []
try:
    for unit in topological_order(units):
        dep_flags = ",".join(f"blocks:{id}" for id in unit.dependency_ids)
        result = bd_create(
            title=unit.title,
            type=unit.type,
            priority=unit.priority,
            deps=dep_flags,
            description=unit.plan_md,
            design=unit.claude_md,
            acceptance=unit.acceptance,
            notes=json.dumps(unit.metadata),
        )
        created_ids.append(result.id)
        unit.bead_id = result.id
except Exception as e:
    # Cleanup: close all created beads
    for id in created_ids:
        bd_close(id, reason=f"decomposition failed: {e}")
    raise DecompositionError(f"Failed at bead {unit.title}: {e}")
```

### Step 12: Write audit log

Append to `.fracture/logs/YYYY-MM-DD-{task_hash}.jsonl`:

```json
{
  "type": "decomposition",
  "timestamp": "ISO8601",
  "task": "original task description",
  "model": "claude-sonnet-4-20250514 | qwen3.5 | etc",
  "dry_run": false,
  "tersecontext_queries": [
    {
      "type": "semantic_search",
      "query": "authentication middleware",
      "results_count": 4,
      "paths_returned": ["src/middleware/auth.js", "..."]
    }
  ],
  "beads": [
    {
      "id": "bd-a1b2",
      "title": "...",
      "phase": 1,
      "depends_on": [],
      "parallel_with": ["bd-c3d4"],
      "file_manifest": {
        "creates": [],
        "modifies": ["src/models/user.js"],
        "reads": ["src/config/database.js"]
      },
      "plan_md_length": 120,
      "claude_md_length": 40,
      "estimated_hours": 2,
      "rationale": "why this is a separate bead"
    }
  ],
  "phases": [
    {"phase": 1, "beads": ["bd-a1b2", "bd-c3d4"], "gate": "validate models"},
    {"phase": 2, "beads": ["bd-e5f6"], "gate": "test integration"}
  ],
  "recursion_events": [
    {
      "parent_unit": "original unit title",
      "reason": "estimated_hours 5 > max 3",
      "sub_units_produced": 3,
      "depth": 1
    }
  ],
  "validation": {
    "conflicts_found": 0,
    "correction_rounds": 1,
    "file_path_fixes": ["moved src/new-middleware.js from modifies to creates"]
  }
}
```

Log directory defaults to `.fracture/logs/` in the project directory. Configurable in `fracture.yaml`.

---

## Structured Notes Format

The `--notes` field on each bead uses a structured JSON format so the `validate` tool can parse file manifests reliably:

```json
{
  "fracture": {
    "version": 1,
    "file_manifest": {
      "creates": ["src/middleware/permissions.js"],
      "modifies": ["src/middleware/auth.js"],
      "reads": ["src/config/jwt.js"]
    },
    "phase": 1,
    "parallel_with": ["bd-c3d4"],
    "decomposition_id": "2026-03-31-a1b2c3d4",
    "estimated_hours": 2
  }
}
```

The `validate` tool reads this JSON from notes to check for write conflicts.

---

## Feedback Loop

After a bead is closed, the executor (or a hook) can report what actually happened:

```bash
# The executor reports actual files changed
fracture feedback --bead bd-a1b2 \
  --actual-creates src/middleware/permissions.js \
  --actual-modifies src/middleware/auth.js src/config/jwt.js
```

Fracture compares the predicted manifest against actual changes and logs the accuracy:

```json
{
  "type": "feedback",
  "bead_id": "bd-a1b2",
  "predicted_modifies": ["src/middleware/auth.js"],
  "actual_modifies": ["src/middleware/auth.js", "src/config/jwt.js"],
  "missed_files": ["src/config/jwt.js"],
  "false_predictions": [],
  "accuracy": 0.67
}
```

Over time, this builds a dataset for understanding where the model's file predictions are weak. Patterns like "always misses config files" or "overestimates creates" become visible.

This feedback does NOT block execution. It's passive reporting for calibration.

---

## MCP Server Interface

### Tool: decompose

```json
{
  "name": "decompose",
  "description": "Decomposes a large task into dependency-ordered beads using codebase context from TerseContext. Creates beads in bd unless dry_run is true.",
  "input_schema": {
    "task": "string",
    "project": "string",
    "dry_run": "boolean (default false)",
    "artifacts": "array of {path, content} — optional fallback if TerseContext unavailable",
    "constraints": {
      "max_bead_hours": "number (default 3)",
      "max_parallel_lanes": "number (default 4)",
      "max_recursion_depth": "number (default 4)"
    }
  },
  "output": {
    "beads": "array of {id, title, phase, depends_on, file_manifest}",
    "phases": "array of {phase, parallel_beads, gate}",
    "log_path": "string",
    "dry_run": "boolean",
    "model_used": "string",
    "tersecontext_available": "boolean"
  }
}
```

### Tool: validate

```json
{
  "name": "validate",
  "description": "Validates existing beads for parallel write conflicts by reading structured file manifests from the notes field.",
  "input_schema": {
    "bead_ids": "array of bead IDs to validate"
  },
  "output": {
    "valid": "boolean",
    "conflicts": "array of {bead_a, bead_b, shared_files}",
    "suggestions": "array of {add_dependency_from, add_dependency_to, reason}"
  }
}
```

### Tool: further_decompose

```json
{
  "name": "further_decompose",
  "description": "Takes a single bead that is too large, decomposes it further, replaces it in the graph with sub-beads.",
  "input_schema": {
    "bead_id": "string",
    "project": "string",
    "dry_run": "boolean (default false)"
  },
  "output": {
    "original_bead_closed": "boolean",
    "sub_beads_created": "array of {id, title, phase, depends_on}",
    "dependencies_rewired": "array of {from, to, reason}"
  }
}
```

### Tool: feedback

```json
{
  "name": "feedback",
  "description": "Reports actual files changed after a bead was executed. Used to calibrate future decompositions.",
  "input_schema": {
    "bead_id": "string",
    "actual_creates": "array of file paths",
    "actual_modifies": "array of file paths"
  },
  "output": {
    "accuracy": "number 0-1",
    "missed_files": "array of file paths",
    "false_predictions": "array of file paths"
  }
}
```

---

## What Fracture Does NOT Do

- **Execute beads.** The executor is a separate system.
- **Manage git or worktrees.** That's the executor's job.
- **Spawn agents.** That's the executor's job.
- **Crawl codebases.** TerseContext does that.
- **Index code.** TerseContext does that.
- **Track bead progress.** Beads (bd) does that.
- **Resolve merge conflicts.** Fracture prevents them by construction.
- **Store files on disk per bead.** Everything lives in the bead fields.

## Dependencies

- **TerseContext** — should be running with the project indexed (falls back to inline artifacts if unavailable)
- **Beads (bd)** — must be initialized in the project
- **An LLM** — Claude API or local model via OpenAI-compatible endpoint

## Configuration

```yaml
# fracture.yaml
tersecontext:
  endpoint: "http://localhost:8000"
  # If TerseContext is an MCP server, use:
  # mcp_server: "tersecontext"

beads:
  project_dir: "/path/to/project"

model:
  provider: "claude"              # "claude" or "local"
  
  # Claude settings
  claude:
    model: "claude-sonnet-4-20250514"
    api_key_env: "ANTHROPIC_API_KEY"
    max_tokens: 4096
  
  # Local LLM settings (OpenAI-compatible endpoint)
  local:
    endpoint: "http://localhost:11434/v1"  # Ollama default
    model: "qwen3.5"
    api_key: ""                            # optional
    max_tokens: 4096

log:
  dir: ".fracture/logs"           # relative to project root

defaults:
  max_bead_hours: 3
  max_parallel_lanes: 4
  max_recursion_depth: 4
  max_correction_rounds: 2
```

---

## Idempotency

Each decomposition gets a `decomposition_id` derived from a hash of the task + timestamp. This ID is stored in every bead's notes field.

Before creating beads, Fracture checks if any existing open beads have the same task hash. If found:

```
- If all beads from the previous decomposition are still open:
    return error "task already decomposed, use further_decompose
    on individual beads or close existing beads first"
    
- If some beads are closed and some are open:
    return error "decomposition in progress, {n} of {m} beads
    still open"
    
- If all beads are closed:
    proceed with new decomposition (re-decompose is allowed
    after completion)
```

This prevents duplicate beads from calling `decompose` twice on the same task.
